import os
import sys
import torch
import time
import whisperx
import gc
import re
import glob
from i18n.i18n import I18nAuto

i18n = I18nAuto()

def apply_safe_globals_hack():
    """
    Workaround for 'Weights only load failed' error in newer PyTorch versions.
    We first try to add safe globals. If that's not enough/fails, we monkeypatch torch.load.
    """
    try:
        import omegaconf
        if hasattr(torch.serialization, 'add_safe_globals'):
            torch.serialization.add_safe_globals([
                omegaconf.listconfig.ListConfig,
                omegaconf.dictconfig.DictConfig,
                omegaconf.base.ContainerMetadata,
                omegaconf.base.Node
            ])
            print("Applied safe globals patch for Omegaconf.")
            
        # Monkeypatch agressivo para garantir compatibilidade com Pyannote/WhisperX antigos
        original_load = torch.load
        
        def safe_load(*args, **kwargs):
            kwargs['weights_only'] = False
            return original_load(*args, **kwargs)
            
        torch.load = safe_load
        print("Applied monkeypatch on torch.load to force weights_only=False.")
        
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARNING] Failed to apply safe globals patch: {e}")

    try:
        import torchaudio
        if not hasattr(torchaudio, 'list_audio_backends'):
            torchaudio.list_audio_backends = lambda: []
            print("Applied monkeypatch on torchaudio.list_audio_backends for PyTorch >= 2.4.")
    except Exception as e:
        pass

def parse_srt(srt_path):
    """
    Parses an SRT file into a list of segments expected by WhisperX alignment.
    [{'start': float, 'end': float, 'text': str}, ...]
    """
    print(f"Parsing SRT: {srt_path}")
    segments = []
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        content = content.replace('\r\n', '\n')
        blocks = content.strip().split('\n\n')
        
        def time_to_seconds(t_str):
            # SRT: 00:00:00,000
            t_str = t_str.replace(',', '.')
            parts = t_str.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
            return 0.0

        for block in blocks:
            lines = block.split('\n')
            # Busca linha de tempo
            for i, line in enumerate(lines):
                if '-->' in line:
                    start_str, end_str = line.split(' --> ')
                    text_lines = lines[i+1:]
                    text = " ".join(text_lines).strip()
                    text = re.sub(r'<[^>]+>', '', text) # Remove tags
                    
                    if text:
                        start = time_to_seconds(start_str.strip())
                        end = time_to_seconds(end_str.strip())
                        segments.append({
                            "start": start,
                            "end": end,
                            "text": text
                        })
                    break
    except Exception as e:
        print(f"Error parsing SRT {srt_path}: {e}")
        return None
    return segments

def parse_vtt(vtt_path):
    """
    Parses a VTT file (WebVTT) into valid segments for WhisperX.
    """
    print(f"Parsing VTT: {vtt_path}")
    segments = []
    try:
        with open(vtt_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        def vtt_time_to_seconds(t_str):
            # VTT: 00:00:00.000 or 00:00.000
            t_str = t_str.strip()
            parts = t_str.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
            return 0.0

        current_entry = {"text": []}
        
        for line in lines:
            line = line.strip()
            if not line:
                # Fim de bloco, salva se tiver tempo e texto
                if "start" in current_entry and current_entry["text"]:
                    full_text = " ".join(current_entry["text"]).strip()
                    # Limpeza extra VTT
                    full_text = re.sub(r'<[^>]+>', '', full_text)
                    full_text = re.sub(r'&[^;]+;', '', full_text)
                    
                    if full_text:
                        segments.append({
                            "start": current_entry["start"],
                            "end": current_entry["end"],
                            "text": full_text
                        })
                current_entry = {"text": []}
                continue
            
            if line.startswith("WEBVTT") or line.startswith("X-TIMESTAMP-MAP") or line.startswith("NOTE"):
                continue

            # Timestamp line: 00:00:05.000 --> 00:00:10.000 (pode ter settings depois)
            if "-->" in line:
                times = line.split("-->")
                start_str = times[0].strip()
                end_str = times[1].strip().split(" ")[0] # remove settings
                current_entry["start"] = vtt_time_to_seconds(start_str)
                current_entry["end"] = vtt_time_to_seconds(end_str)
            else:
                # É texto (se já tivermos timestamps)
                if "start" in current_entry:
                     current_entry["text"].append(line)
                     
        # Salva ultimo bloco se existir
        if "start" in current_entry and current_entry["text"]:
            full_text = " ".join(current_entry["text"]).strip()
            full_text = re.sub(r'<[^>]+>', '', full_text)
            if full_text:
                segments.append({
                    "start": current_entry["start"],
                    "end": current_entry["end"],
                    "text": full_text
                })

    except Exception as e:
        print(f"Error parsing VTT {vtt_path}: {e}")
        return None
    return segments

def transcribe(input_file, model_name='large-v3', project_folder='tmp'):
    device_label = "GPU (CUDA)" if torch.cuda.is_available() else "CPU"
    print(f"  Audio      : {input_file}")
    print(f"  Device     : {device_label}")
    print(f"  Model      : {model_name}")

    start_time = time.time()

    if project_folder is None:
        project_folder = os.path.dirname(input_file)
        if not project_folder:
            project_folder = 'tmp'

    output_folder = project_folder
    os.makedirs(output_folder, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    srt_file = os.path.join(output_folder, f"{base_name}.srt")
    tsv_file = os.path.join(output_folder, f"{base_name}.tsv")
    json_file = os.path.join(output_folder, f"{base_name}.json")

    if os.path.exists(srt_file) and os.path.exists(tsv_file) and os.path.exists(json_file):
        print("  Transcript already exists — skipping.")
        return srt_file, tsv_file

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "float32"

    try:
        apply_safe_globals_hack()

        print("  Loading audio...")
        audio = whisperx.load_audio(input_file)

        if os.path.exists(os.path.join(output_folder, "input.srt")):
            potential_subs = [os.path.join(output_folder, "input.srt")]
        elif os.path.exists(os.path.join(output_folder, "input.vtt")):
            potential_subs = [os.path.join(output_folder, "input.vtt")]
        else:
            potential_subs = []

        start_segments = None
        alignment_only = False
        detected_language = "en"

        if potential_subs:
            sub_path = potential_subs[0]
            print(f"  Official subtitles found: {os.path.basename(sub_path)} — using fast alignment mode")

            if sub_path.endswith('.srt'):
                parsed = parse_srt(sub_path)
            elif sub_path.endswith('.vtt'):
                parsed = parse_vtt(sub_path)
            else:
                parsed = None

            if parsed and len(parsed) > 0:
                start_segments = parsed
                alignment_only = True
                # Infer language from subtitle filename (e.g. input.ar.srt → 'ar')
                # Pattern requires a real extension after the lang code, so 'input.srt' → no match → 'en'
                sub_basename = os.path.basename(sub_path)
                lang_match = re.search(r'input\.([a-z]{2,3})\.(srt|vtt)$', sub_basename)
                detected_language = lang_match.group(1) if lang_match else 'en'

        result = None

        if not (alignment_only and start_segments):
            print(f"  No official subtitles found — running full WhisperX transcription...")
            print(f"  Loading model '{model_name}'...")
            model = whisperx.load_model(
                model_name,
                device,
                compute_type=compute_type,
                asr_options={"hotwords": None}
            )

            batch_size = 2 if device == "cpu" else 16
            result = model.transcribe(audio, batch_size=batch_size, chunk_size=10)

            detected_language = result["language"]
            start_segments = result["segments"]
            print(f"  Detected language: {detected_language}")

            del model
            gc.collect()
            if device == "cuda":
                torch.cuda.empty_cache()

        print(f"  Aligning word timestamps (language: {detected_language})...")
        try:
            model_a, metadata = whisperx.load_align_model(language_code=detected_language, device=device)
            aligned_result = whisperx.align(start_segments, model_a, metadata, audio, device, return_char_alignments=False)
            result = aligned_result
            result["language"] = detected_language

            if device == "cuda":
                del model_a
                torch.cuda.empty_cache()

        except Exception as e:
            print(f"  [WARNING] Alignment failed: {e}")
            if alignment_only:
                print("  Falling back to original subtitle timestamps (word-level timing may be approximate).")
                result = {"segments": start_segments, "language": detected_language}
            else:
                print("  Continuing with raw transcription timestamps.")

        print("  Saving transcript files (SRT / TSV / JSON)...")
        from whisperx.utils import get_writer

        save_options = {"highlight_words": False, "max_line_count": None, "max_line_width": None}
        get_writer("srt", output_folder)(result, input_file, save_options)
        get_writer("tsv", output_folder)(result, input_file, save_options)
        get_writer("json", output_folder)(result, input_file, save_options)

        elapsed = time.time() - start_time
        print(f"  Transcription completed in {int(elapsed//60)}m {int(elapsed%60)}s.")

    except Exception as e:
        print(f"\n[ERROR] Transcription failed: {e}")
        import traceback
        traceback.print_exc()
        raise

    if not os.path.exists(srt_file):
        print(f"[WARNING] Expected SRT file not found after transcription: {srt_file}")

    return srt_file, tsv_file
