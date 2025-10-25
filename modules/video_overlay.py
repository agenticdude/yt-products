"""
Video Overlay Module - GPU ONLY (No CPU Fallback)
100% GPU-optimized with full video encoding
Requires NVIDIA GPU with CUDA support
"""

import subprocess
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_video_duration(video_path):
    """Get video duration in seconds"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe error: {result.stderr.decode(errors='ignore')}")
    try:
        return float(result.stdout.decode().strip())
    except:
        raise RuntimeError("Unable to parse duration")


def apply_video_overlay_smart(
    main_video_path,
    overlay_video_path,
    output_path,
    timing_mode="custom_time",
    start_time=0,
    end_time=None,
    position="top_right",
    size_percent=20,
    remove_green=True,
    green_similarity=0.3,
    green_blend=0.1,
    keep_overlay_audio=False,
    quality_preset="high_quality",
    optimize=True
):
    """
    Apply video overlay with GPU - Full video encoding
    
    Args:
        main_video_path: Path to main video
        overlay_video_path: Path to overlay video
        output_path: Path for output
        timing_mode: "full_duration", "custom_time", "overlay_duration"
        start_time: Overlay start time in seconds
        end_time: Overlay end time in seconds (None = auto)
        position: Overlay position (top_left, top_right, bottom_left, bottom_right, center)
        size_percent: Overlay size as percentage
        remove_green: Remove green screen
        green_similarity: Green screen similarity threshold
        green_blend: Green screen blend amount
        keep_overlay_audio: Mix both audios (True) or keep only main video audio (False)
        quality_preset: Quality preset
        optimize: Unused parameter (kept for compatibility)
    
    Returns:
        Path to output video
    """
    
    main_duration = get_video_duration(main_video_path)
    overlay_duration = get_video_duration(overlay_video_path)
    
    # Determine actual overlay timing
    if timing_mode == "full_duration":
        actual_start = 0
        actual_end = main_duration
    elif timing_mode == "overlay_duration":
        actual_start = start_time
        actual_end = start_time + overlay_duration
    else:  # custom_time
        actual_start = start_time
        actual_end = end_time if end_time is not None else main_duration
    
    # Ensure end time doesn't exceed video duration
    actual_end = min(actual_end, main_duration)
    overlay_segment_duration = actual_end - actual_start
    
    logger.info(f"Main video duration: {main_duration}s")
    logger.info(f"Overlay segment: {actual_start}s to {actual_end}s ({overlay_segment_duration}s)")
    logger.info("Using full GPU encode method")
    
    # Always use full GPU encode
    return _apply_overlay_full_encode(
        main_video_path, overlay_video_path, output_path,
        actual_start, actual_end,
        position, size_percent, remove_green, green_similarity,
        green_blend, keep_overlay_audio, quality_preset
    )


def _apply_overlay_full_encode(
    main_video_path, overlay_video_path, output_path,
    start_time, end_time,
    position, size_percent, remove_green, green_similarity,
    green_blend, keep_overlay_audio, quality_preset
):
    """
    Full GPU overlay method (entire video encoding)
    
    Audio Behavior:
    - keep_overlay_audio=False: Keep only main video audio, remove overlay audio
    - keep_overlay_audio=True: Mix both main video audio AND overlay audio together
    """
    
    logger.info("Applying GPU overlay using full encode method")
    
    # Build video filter complex
    scale_filter = f"scale=iw*{size_percent/100}:ih*{size_percent/100}"
    
    position_map = {
        "top_left": "10:10",
        "top_right": "main_w-overlay_w-10:10",
        "bottom_left": "10:main_h-overlay_h-10",
        "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    }
    overlay_position = position_map.get(position, "10:10")
    
    # Video overlay filter
    if remove_green:
        chroma_key = f"colorkey=0x00FF00:{green_similarity}:{green_blend}"
        video_filter = f"[1:v]format=yuv420p,{scale_filter},{chroma_key}[ovr];[0:v][ovr]overlay={overlay_position}:enable='between(t,{start_time},{end_time})'[vout]"
    else:
        video_filter = f"[1:v]format=yuv420p,{scale_filter}[ovr];[0:v][ovr]overlay={overlay_position}:enable='between(t,{start_time},{end_time})'[vout]"
    
    # Audio handling
    if keep_overlay_audio:
        # Mix both audios: main video audio + overlay audio
        filter_complex = video_filter + ";[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        audio_map = ["-map", "[vout]", "-map", "[aout]"]
        logger.info("Audio: Mixing main video audio + overlay audio")
    else:
        # Keep only main video audio, ignore overlay audio
        filter_complex = video_filter
        audio_map = ["-map", "[vout]", "-map", "0:a?"]
        logger.info("Audio: Keeping only main video audio")
    
    # GPU-ONLY quality settings
    quality_settings = {
        "ultra_fast": {"gpu_preset": "p4", "cq": "23"},
        "high_quality": {"gpu_preset": "p6", "cq": "19"},
        "maximum_quality": {"gpu_preset": "p7", "cq": "17"}
    }
    
    selected = quality_settings.get(quality_preset, quality_settings["high_quality"])
    
    # Build FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", str(main_video_path),
        "-i", str(overlay_video_path),
        "-filter_complex", filter_complex
    ]
    
    # Add audio mapping
    cmd.extend(audio_map)
    
    # GPU video encoding
    cmd.extend([
        "-c:v", "h264_nvenc",
        "-preset", selected["gpu_preset"],
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", selected["cq"],
        "-profile:v", "high",
        "-spatial-aq", "1",
        "-temporal-aq", "1"
    ])
    
    # Audio encoding
    cmd.extend([
        "-c:a", "aac",
        "-b:a", "320k"
    ])
    
    # Output file
    cmd.append(str(output_path))
    
    logger.info(f"Running FFmpeg command...")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=3600)
    
    if result.returncode != 0:
        raise RuntimeError(f"GPU overlay failed: {result.stderr.decode(errors='ignore')}")
    
    logger.info(f"✓ Full GPU overlay complete: {output_path}")
    return str(output_path)


if __name__ == "__main__":
    pass