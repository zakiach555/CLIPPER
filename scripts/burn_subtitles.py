import os
import shutil
import subprocess
import sys

_SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
_WORKING_DIR  = os.path.dirname(_SCRIPTS_DIR)
_CUSTOM_FONTS = os.path.join(_WORKING_DIR, "arfonts-lyon-arabic-display_all")

def _safe_fonts_dir():
    """Copy custom fonts to a space-free path for reliable libass lookup.
    On Windows, libass truncates fontsdir at the first space.
    On Linux (Colab), use /tmp/vcfonts."""
    if os.name == 'nt':
        drive = os.path.splitdrive(_WORKING_DIR)[0] or "C:"
        safe = os.path.join(drive + "\\", "vcfonts")
    else:
        safe = "/tmp/vcfonts"
    os.makedirs(safe, exist_ok=True)
    if os.path.isdir(_CUSTOM_FONTS):
        for fname in os.listdir(_CUSTOM_FONTS):
            if fname.lower().endswith((".otf", ".ttf")):
                dst = os.path.join(safe, fname)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(_CUSTOM_FONTS, fname), dst)
    return safe

def burn_video_file(video_path, subtitle_path, output_path):
    """
    Burns subtitles into a single video file.
    """
    # Normalize path separators and escape ffmpeg filter special characters.
    # Also escape apostrophes — they break single-quoted filter args (e.g. "Duolingo's").
    def _ffmpeg_escape(path):
        p = path.replace('\\', '/')
        if os.name == 'nt':
            p = p.replace(':', '\\:')
        p = p.replace("'", "\\'")
        return p

    subtitle_file_ffmpeg = _ffmpeg_escape(subtitle_path)

    # Ensure fonts live at a space-free path so libass can find them reliably.
    fonts_dir = _ffmpeg_escape(_safe_fonts_dir())
    sub_filter = f"subtitles='{subtitle_file_ffmpeg}':fontsdir='{fonts_dir}'"

    def run_ffmpeg(encoder, preset, additional_args=[]):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-hide_banner",
            '-i', video_path,
            '-vf', sub_filter,
            '-c:v', encoder,
            '-preset', preset,
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',
            output_path
        ] + additional_args
        subprocess.run(cmd, check=True, capture_output=True)

    try:
        run_ffmpeg("libx264", "fast")
        return True, "CPU Success"
    except subprocess.CalledProcessError as e2:
        err_msg = f"[ERROR] Failed to burn subtitles into {os.path.basename(video_path)}: {e2}"
        if e2.stderr:
            stderr_text = e2.stderr.decode('utf-8', errors='replace')
            err_msg += f"\n  FFmpeg: {stderr_text.strip()}"
        print(err_msg)
        return False, err_msg
    except Exception as e:
        return False, str(e)

def burn(project_folder="tmp"):
    # Converter para absoluto para não ter erro no filtro do ffmpeg
    if project_folder and not os.path.isabs(project_folder):
        project_folder_abs = os.path.abspath(project_folder)
    else:
        project_folder_abs = project_folder

    # Caminhos das pastas
    subs_folder = os.path.join(project_folder_abs, 'subs_ass')
    videos_folder = os.path.join(project_folder_abs, 'final')
    output_folder = os.path.join(project_folder_abs, 'burned_sub')  # Pasta para salvar os vídeos com legendas

    # Cria a pasta de saída se não existir
    os.makedirs(output_folder, exist_ok=True)
    
    if not os.path.exists(videos_folder):
        print(f"[ERROR] Final videos folder not found: {videos_folder}")
        return

    # Itera sobre os arquivos de vídeo na pasta final
    files = os.listdir(videos_folder)
    if not files:
        print("[WARNING] No video files found in 'final' folder — nothing to burn.")
        return

    for video_file in files:
        if video_file.endswith(('.mp4', '.mkv', '.avi')):  # Formatos suportados
            # Se for temp file (ex: temp_video_no_audio), ignora se existir a versão final
            if "temp_video_no_audio" in video_file:
                continue

            # Extrai o nome base do vídeo (sem extensão)
            video_name = os.path.splitext(video_file)[0]
            
            # Define o caminho para a legenda correspondente
            subtitle_file = os.path.join(subs_folder, f"{video_name}.ass")
            
            # Tentar também com sufixo _processed caso a convenção seja diferente
            if not os.path.exists(subtitle_file):
                subtitle_file_processed = os.path.join(subs_folder, f"{video_name}_processed.ass")
                if os.path.exists(subtitle_file_processed):
                    subtitle_file = subtitle_file_processed
            
            # Verifica se a legenda existe
            if os.path.exists(subtitle_file):
                # Define o caminho de saída para o vídeo com legendas
                output_file = os.path.join(output_folder, f"{video_name}_subtitled.mp4")

                print(f"  Burning subtitles: {video_name}...")
                success, msg = burn_video_file(os.path.join(videos_folder, video_file), subtitle_file, output_file)
                if success:
                    print(f"  Done: {os.path.basename(output_file)}")
                else:
                    print(f"  [ERROR] Burn failed: {msg}")
            else:
                print(f"  [WARNING] No subtitle file found for: {video_name} (expected: {os.path.basename(subtitle_file)})")
