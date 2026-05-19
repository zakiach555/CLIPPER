import json
import re
import os

# Arabic Unicode block: U+0600–U+06FF
_ARABIC_RE = re.compile(r'[؀-ۿ]')

def _has_arabic(text):
    return bool(_ARABIC_RE.search(text))

_SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
_WORKING_DIR  = os.path.dirname(_SCRIPTS_DIR)
_CUSTOM_FONTS = os.path.join(_WORKING_DIR, "arfonts-lyon-arabic-display_all")

def _arabic_safe_font(font):
    """Return font if Arabic-capable and found in the custom fonts folder or Windows Fonts.
    Falls back to Tahoma (always present on Windows, full Arabic coverage)."""
    arabic_capable = {
        "arial", "arial unicode ms", "tahoma", "calibri", "verdana",
        "times new roman", "microsoft sans serif", "simplified arabic",
        "traditional arabic", "arabic typesetting", "segoe ui",
        "noto sans arabic", "montserrat arabic",
        # Lyon Arabic Display family
        "lyon arabic display",
        "lyon arabic display black",
        "lyon arabic display bold",
        "lyon arabic display medium",
        "lyon arabic display light",
        "lyon arabic display regular",
    }
    if font.lower() not in arabic_capable:
        return "Tahoma"

    needle = font.lower().replace(" ", "").replace("-", "")

    def _found_in(folder):
        if not os.path.isdir(folder):
            return False
        try:
            for fname in os.listdir(folder):
                base = os.path.splitext(fname)[0].lower().replace(" ", "").replace("-", "").replace("_", "")
                if needle in base:
                    return True
        except OSError:
            pass
        return False

    if _found_in(_CUSTOM_FONTS) or _found_in(r"C:\Windows\Fonts"):
        return font
    return "Tahoma"

def _detect_json_arabic(json_data):
    """Return True if any word in the JSON segments contains Arabic characters."""
    for seg in json_data.get("segments", []):
        for w in seg.get("words", []):
            if _has_arabic(w.get("word", "")):
                return True
    return False

def format_time_ass(time_seconds):
    hours = int(time_seconds // 3600)
    minutes = int((time_seconds % 3600) // 60)
    seconds = int(time_seconds % 60)
    centiseconds = int((time_seconds % 1) * 100)
    return f"{hours:01}:{minutes:02}:{seconds:02}.{centiseconds:02}"

def generate_ass_from_file(input_path, output_path, project_folder,
                           base_color, base_size, highlight_size, highlight_color,
                           words_per_block, gap_limit, mode, vertical_position, alignment,
                           font, outline_color, shadow_color, bold, italic, underline,
                            strikeout, border_style, outline_thickness, shadow_size, uppercase,
                            face_modes={}, remove_punctuation=True,
                            speaker_name="", speaker_title="", speaker_duration=0):
    """
    Generates a single ASS file from a JSON input.
    """
    
    # 1. Load Timeline Data (if exists)
    # 1. Load Timeline Data (if exists)
    filename = os.path.basename(input_path)
    base_name = os.path.splitext(filename)[0]

    # Try renamed timeline first (e.g. 000_Title_timeline.json)
    # Subtitle is 000_Title_processed.json -> 000_Title_timeline.json
    renamed_timeline_name = base_name.replace("_processed", "") + "_timeline.json"
    renamed_timeline_path = os.path.join(project_folder, "final", renamed_timeline_name)

    timeline_data = None
    idx = None

    if os.path.exists(renamed_timeline_path):
        try:
             with open(renamed_timeline_path, "r") as tf:
                 timeline_data = json.load(tf)
        except: pass
    
    # Check for Index (outputXXX or XXX_Title)
    match_output = re.search(r"output(\d+)", filename)
    match_index = re.search(r"^(\d{3})_", filename)

    if match_output:
        idx = int(match_output.group(1))
    elif match_index:
        idx = int(match_index.group(1))

    # Fallback to temp timeline if not already loaded and idx known
    if not timeline_data and idx is not None:
         csv_timeline = os.path.join(project_folder, "final", f"temp_video_no_audio_{idx}_timeline.json")
         if os.path.exists(csv_timeline):
             try:
                 with open(csv_timeline, "r") as tf:
                     timeline_data = json.load(tf)
             except: pass

    # 2. Determine Style Overrides (Face Mode)
    # Determine static alignment (fallback)
    key = base_name
    if idx is not None:
        key = f"output{str(idx).zfill(3)}"
    
    current_alignment = alignment
    current_vertical_position = vertical_position
    
    mode_face = face_modes.get(key)
    if mode_face == "2" and not timeline_data: # Only use static if no timeline
        current_alignment = 5 
        current_vertical_position = 0 

    # 3. Load JSON
    try:
        with open(input_path, "r", encoding="utf-8") as file:
            json_data = json.load(file)
        
        segments_count = len(json_data.get('segments', []))
        print(f"[DEBUG] Loaded {input_path}: Found {segments_count} segments.")
    except Exception as e:
        print(f"[ERROR] Loading JSON {input_path}: {e}")
        return

    # 4. Generate Content
    is_arabic = _detect_json_arabic(json_data)
    effective_font = _arabic_safe_font(font) if is_arabic else font
    # WrapStyle 2 = no word wrapping (best for RTL / complex scripts)
    wrap_style = 2 if is_arabic else 1

    header_ass = f"""[Script Info]
Title: Dynamic Subtitles
ScriptType: v4.00+
PlayDepth: 0
PlayResX: 360
PlayResY: 640
WrapStyle: {wrap_style}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{effective_font},{base_size},{base_color},&H00000000,{outline_color},{shadow_color},{bold},{italic},{underline},{strikeout},100,100,0,0,{border_style},{outline_thickness},{shadow_size},{alignment},-2,-2,{vertical_position},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    total_lines_written = 0
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header_ass)

        # Speaker tag (Zone A): gold name + white title, top-left, timed
        spk_name = str(speaker_name).strip()
        spk_title = str(speaker_title).strip()
        spk_dur = float(speaker_duration) if speaker_duration else 0.0
        if spk_name and spk_dur > 0:
            end_tag = format_time_ass(spk_dur)
            gold = "&H00279FEF&"
            tag_line = f"{{\\an7\\pos(15,85)\\fs20\\c{gold}\\b1}}{spk_name}"
            if spk_title:
                tag_line += f"\\N{{\\fs13\\c&H00FFFFFF&\\b0}}{spk_title}"
            if _has_arabic(tag_line):
                def _inject_rtl_local(text):
                    rtl = "‏"
                    if text.startswith("{"):
                        closing = text.find("}")
                        if closing != -1:
                            return text[:closing+1] + rtl + text[closing+1:]
                    return rtl + text
                if "\\N" in tag_line:
                    parts = tag_line.split("\\N")
                    tag_line = "\\N".join(_inject_rtl_local(p) for p in parts)
                else:
                    tag_line = _inject_rtl_local(tag_line)
            f.write(f"Dialogue: 0,0:00:00.00,{end_tag},Default,,0,0,0,,{tag_line}\n")

        last_end_time = 0.0

        for segment in json_data.get('segments', []):
            words = segment.get('words', [])
            total_words = len(words)

            i = 0
            while i < total_words:
                block = []
                while len(block) < words_per_block and i < total_words:
                    current_word = words[i]
                    if 'word' in current_word:
                        if remove_punctuation:
                            cleaned_word = re.sub(r'[.,!?;]', '', current_word['word'])
                            block.append({**current_word, 'word': cleaned_word})
                        else:
                            block.append(current_word)

                        if i + 1 < total_words:
                            next_word = words[i + 1]
                            if 'start' not in next_word or 'end' not in next_word:
                                if remove_punctuation:
                                    next_cleaned_word = re.sub(r'[.,!?;]', '', next_word['word'])
                                    block[-1]['word'] += " " + next_cleaned_word
                                else:
                                    block[-1]['word'] += " " + next_word['word']
                                i += 1
                    i += 1


                # Uppercase transformation
                if uppercase:
                     for w_item in block:
                         if 'word' in w_item:
                             w_item['word'] = w_item['word'].upper()

                start_times = [word.get('start', 0) for word in block]
                end_times = [word.get('end', 0) for word in block]
                
                if not start_times: continue

                for j in range(len(block)):

                    # ── TWO-TIER MODE ──────────────────────────────────────────
                    # One ASS event per block: top line = white context,
                    # bottom line = gold punchline (Quotologie style).
                    if mode == "two_tier":
                        if j != 0:
                            continue          # write only one event per block
                        start_sec = start_times[0]
                        end_sec   = end_times[-1]
                    else:
                        start_sec = start_times[j]
                        end_sec   = end_times[j]
                    # ──────────────────────────────────────────────────────────

                    # Prevent overlap and close gaps
                    if start_sec - last_end_time < gap_limit:
                        start_sec = last_end_time

                    # Ensure valid duration
                    if end_sec < start_sec:
                        end_sec = start_sec

                    start_time_ass = format_time_ass(start_sec)
                    end_time_ass = format_time_ass(end_sec)

                    last_end_time = end_sec

                    line = ""
                    if mode == "highlight":
                        # For Arabic, fribidi handles RTL reordering automatically after we
                        # inject a strong RTL mark. Do NOT reverse words here — reversing
                        # combined with bidi would double-flip the order back to LTR.
                        for k, word_data in enumerate(block):
                            word = word_data['word']
                            if k == j:
                                line += f"{{\\fs{highlight_size}\\c{highlight_color}}}{word} "
                            else:
                                line += f"{{\\fs{base_size}\\c{base_color}}}{word} "
                        line = line.strip()

                    elif mode == "two_tier":
                        n = len(block)
                        # Split: first ~half = context (white/small), rest = punchline (gold/large)
                        split = max(1, n // 2)
                        top_words = " ".join(w['word'] for w in block[:split]).strip()
                        bot_words = " ".join(w['word'] for w in block[split:]).strip()
                        if not bot_words:          # only one word → all gold on bottom
                            top_words = ""
                            bot_words = block[0]['word'].strip()
                        top_part = f"{{\\fs{base_size}\\c{base_color}}}{top_words}" if top_words else ""
                        bot_part = f"{{\\fs{highlight_size}\\c{highlight_color}}}{bot_words}"
                        line = f"{top_part}\\N{bot_part}" if top_part else bot_part

                    elif mode == "no_highlight" or mode == "sem_higlight":
                        line = " ".join(word_data['word'] for word_data in block).strip()

                    elif mode == "palavra_por_palavra":
                        line = block[j]['word'].strip()

                    else:
                        # Fallback / No Highlight
                        line = " ".join(word_data['word'] for word_data in block).strip()

                    # Check dynamic timeline for this specific time
                    pos_tag = ""

                    if timeline_data:
                        # Verify if middle of subtitle is in a '2' mode segment
                        mid_time = (start_sec + end_sec) / 2
                        found_mode = "1"
                        for seg in timeline_data:
                            if seg['start'] <= mid_time <= seg['end']:
                                found_mode = seg['mode']
                                break

                        if found_mode == "2":
                             # Force Center (Relative to PlayRes 360x640)
                             x_pos = 360 // 2  # 180
                             y_pos = 640 // 2  # 320
                             current_line_alignment = 5 # Center

                             # Apply Override Tags: {\an5\pos(x,y)}
                             pos_tag = f"{{\\an{current_line_alignment}\\pos({x_pos},{y_pos})}}"
                             final_line = f"{pos_tag}{line}"
                        else:
                             # Mode 1: Respect User Config (Standard Style)
                             final_line = line
                    else:
                        final_line = line

                    if is_arabic and _has_arabic(final_line):
                        rtl_mark = "‏"
                        # Fix punctuation resetting bidi direction
                        final_line = re.sub(r'([.,،؛؟!?;])', r'\1' + rtl_mark, final_line)
                        # Inject RTL mark at the start of each visual line so fribidi
                        # sets RTL as paragraph base direction for both lines.
                        def _inject_rtl(text):
                            if text.startswith("{"):
                                closing = text.find("}")
                                if closing != -1:
                                    return text[:closing+1] + rtl_mark + text[closing+1:]
                            return rtl_mark + text
                        if "\\N" in final_line:
                            parts = final_line.split("\\N")
                            final_line = "\\N".join(_inject_rtl(p) for p in parts)
                        else:
                            final_line = _inject_rtl(final_line)

                    f.write(f"Dialogue: 0,{start_time_ass},{end_time_ass},Default,,0,0,0,,{final_line}\n")
                    total_lines_written += 1
    
    if total_lines_written == 0:
        print(f"[WARN] No dialogue lines written for {input_path}")
    else:
        print(f"[DEBUG] Wrote {total_lines_written} lines to {output_path}")


def adjust(base_color, base_size, highlight_size, highlight_color, words_per_block, gap_limit, mode, vertical_position, alignment, font, outline_color, shadow_color, bold, italic, underline, strikeout, border_style, outline_thickness, shadow_size, uppercase=False, project_folder="tmp", **kwargs):
    
    # Input and Output Directories
    input_dir = os.path.join(project_folder, "subs")
    output_dir = os.path.join(project_folder, "subs_ass")

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    remove_punctuation = kwargs.get('remove_punctuation', True)
    speaker_name = kwargs.get('speaker_name', '')
    speaker_title = kwargs.get('speaker_title', '')
    speaker_duration = kwargs.get('speaker_duration', 0)

    # Load face modes if available
    face_modes = {}
    modes_file = os.path.join(project_folder, "face_modes.json")
    if os.path.exists(modes_file):
        try:
             with open(modes_file, "r") as f:
                 face_modes = json.load(f)
             print("Loaded face modes for dynamic subtitle positioning.")
        except Exception as e:
            print(f"Could not load face modes: {e}")

    # Process all JSON files in input directory
    # Process all JSON files in input directory
    if not os.path.exists(input_dir):
        print(f"[ERROR] Subtitle folder missing: {input_dir}")
        raise FileNotFoundError(f"Subtitle folder missing at {input_dir}. Ensure transcription completed successfully.")

    for filename in os.listdir(input_dir):
        if filename.endswith(".json"):
            input_path = os.path.join(input_dir, filename)
            output_filename = os.path.splitext(filename)[0] + ".ass"
            output_path = os.path.join(output_dir, output_filename)
            
            generate_ass_from_file(input_path, output_path, project_folder,
                           base_color, base_size, highlight_size, highlight_color,
                           words_per_block, gap_limit, mode, vertical_position, alignment,
                           font, outline_color, shadow_color, bold, italic, underline,
                           strikeout, border_style, outline_thickness, shadow_size, uppercase,
                           face_modes, remove_punctuation,
                           speaker_name, speaker_title, speaker_duration)

            print(f"Processed file: {filename} -> {output_filename}")

    print("All JSON files processed and converted to ASS.")