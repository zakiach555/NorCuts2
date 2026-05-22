import os
import subprocess
import sys

# Arabic renderer — used for font caching before any burn step
try:
    from scripts import renderer_arabic as _ar
except ImportError:
    try:
        import renderer_arabic as _ar   # type: ignore
    except ImportError:
        _ar = None

# Use a simple path with no spaces so libass fontsdir works reliably on Windows
_FONTS_DIR = r'C:\vcfonts'

def _ensure_fonts_cached():
    """
    Cache Arabic-capable fonts to C:\\vcfonts via renderer_arabic.
    Falls back to creating an empty directory when renderer_arabic is unavailable.
    """
    if _ar is not None:
        _ar.ensure_fonts_cached()
    else:
        os.makedirs(_FONTS_DIR, exist_ok=True)

_cached_encoder = None

def _detect_best_encoder():
    global _cached_encoder
    if _cached_encoder is not None:
        return _cached_encoder
    test_base = ["ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-frames:v", "1"]
    for encoder, preset in [("h264_nvenc", "p1"), ("h264_qsv", "medium"), ("h264_mf", "medium")]:
        try:
            result = subprocess.run(
                test_base + ["-c:v", encoder, "-f", "null", "-"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                print(f"[burn] Using hardware encoder: {encoder}")
                _cached_encoder = (encoder, preset)
                return _cached_encoder
        except Exception:
            pass
    _cached_encoder = ("libx264", "ultrafast")
    return _cached_encoder


def burn_video_file(video_path, subtitle_path, output_path):
    """
    Burns subtitles into a single video file.
    """
    _ensure_fonts_cached()
    subtitle_file_ffmpeg = subtitle_path.replace('\\', '/').replace(':', '\\:')

    # Build subtitle + cinematic filter chain
    # unsharp: mild sharpening for crisp edges
    # eq: slight contrast/saturation boost for cinematic pop
    cinematic = "unsharp=5:5:0.6:5:5:0.0,eq=contrast=1.05:brightness=0.02:saturation=1.1"
    sub_filter = f"{cinematic},subtitles='{subtitle_file_ffmpeg}':fontsdir='C\\:/vcfonts'"

    encoder, preset = _detect_best_encoder()

    extra = []
    if encoder == "h264_qsv":
        extra = ["-global_quality", "20"]
    elif encoder in ("h264_nvenc", "h264_amf"):
        extra = ["-b:v", "12M"]
    else:  # libx264
        extra = ["-crf", "18", "-preset", "slow"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-hide_banner",
        "-i", video_path,
        "-vf", sub_filter,
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        output_path,
    ] + extra

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True, f"{encoder} Success"
    except subprocess.CalledProcessError as e:
        if encoder != "libx264":
            print(f"[burn] {encoder} failed, falling back to libx264...")
            cmd_cpu = [
                "ffmpeg", "-y", "-loglevel", "error", "-hide_banner",
                "-i", video_path,
                "-vf", sub_filter,
                "-c:v", "libx264", "-preset", "slow",
                "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "copy", output_path,
            ]
            try:
                subprocess.run(cmd_cpu, check=True, capture_output=True)
                return True, "CPU Success"
            except subprocess.CalledProcessError as e2:
                err_msg = f"FATAL burn error {os.path.basename(video_path)}: {e2}"
                if e2.stderr:
                    err_msg += f" | {e2.stderr.decode('utf-8', errors='replace')}"
                print(err_msg)
                return False, err_msg
        err_msg = f"FATAL burn error {os.path.basename(video_path)}: {e}"
        if e.stderr:
            err_msg += f" | {e.stderr.decode('utf-8', errors='replace')}"
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
        print(f"Pasta de vídeos finais não encontrada: {videos_folder}")
        return

    # Itera sobre os arquivos de vídeo na pasta final
    files = os.listdir(videos_folder)
    if not files:
        print("Nenhum arquivo encontrado em 'final' para queimar legendas.")
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

                print(f"Burning: {video_name}...")
                success, msg = burn_video_file(os.path.join(videos_folder, video_file), subtitle_file, output_file)
                if success:
                    print(f"Done: {output_file}")
                else:
                    print(f"Fail: {msg}")
            else:
                print(f"Legenda não encontrada para: {video_name} em {subtitle_file}")
