import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import shutil
from multiprocessing import Pool

# Load environment variables from .env file
load_dotenv()

# Mapping for custom names
directory_labels = {
    "lumi1.54ef4448a02c": "livingRoom",
    "lumi1.54ef4463a098": "swBed"
}

def is_mounted(mount_point):
    """Check if the mount point is already mounted."""
    result = subprocess.run(['mount'], capture_output=True, text=True)
    return mount_point in result.stdout

def mount_smb_share(tailscale_ip, share_name, mount_point, username, password):
    mount_point_path = Path(mount_point).resolve()
    if not mount_point_path.exists():
        mount_point_path.mkdir(parents=True, exist_ok=True)

    if is_mounted(str(mount_point_path)):
        print(f"{mount_point_path} is already mounted.")
        return

    mount_cmd = [
        'mount_smbfs',
        f'//{username}:{password}@{tailscale_ip}/{share_name}',
        str(mount_point_path)
    ]

    try:
        subprocess.run(mount_cmd, check=True)
        print(f"Mounted {share_name} at {mount_point_path}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to mount SMB share: {e}")
        raise

def process_chunk(chunk_id, chunk_files, output_dir, speed):
    list_file_path = output_dir / f'files_{chunk_id}.txt'
    chunk_output_file = output_dir / f'chunk_{chunk_id}.mp4'
    with open(list_file_path, 'w') as f:
        for mp4 in chunk_files:
            f.write(f"file '{mp4}'\n")
    ffmpeg_cmd = [
        'ffmpeg',
        '-hwaccel', 'videotoolbox',
        '-f', 'concat',
        '-safe', '0',
        '-i', str(list_file_path),
        '-filter:v', f'setpts=PTS/{speed}',
        '-c:v', 'hevc_videotoolbox',
        '-b:v', '2M',  # Set target bitrate to 2 Mbps
        '-pix_fmt', 'yuv420p',
        '-an',  # Disable audio
        str(chunk_output_file)
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        print(f"Processed chunk {chunk_id} into {chunk_output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to process chunk {chunk_id}: {e}")
    finally:
        list_file_path.unlink()
    return chunk_output_file

def create_time_lapse_parallel(source_dir, output_file, speed=60):
    source_path = Path(source_dir).resolve()
    output_path = Path(output_file).resolve()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    mp4_files = sorted(source_path.glob('*.mp4'))
    if not mp4_files:
        print("No MP4 files found to process.")
        return

    num_processes = os.cpu_count() or 12  
    chunk_size = len(mp4_files) // num_processes + 1
    chunks = [mp4_files[i:i + chunk_size] for i in range(0, len(mp4_files), chunk_size)]

    with Pool(num_processes) as pool:
        results = [
            pool.apply_async(process_chunk, args=(i, chunk, output_dir, speed))
            for i, chunk in enumerate(chunks)
        ]
        chunk_output_files = [res.get() for res in results]

    # Merge the chunk output files
    chunks_list_file = output_dir / 'chunks_list.txt'
    with open(chunks_list_file, 'w') as f:
        for chunk_file in chunk_output_files:
            f.write(f"file '{chunk_file}'\n")

    merge_cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', str(chunks_list_file),
        '-c', 'copy',
        '-an',  # Disable audio
        str(output_path)
    ]
    try:
        subprocess.run(merge_cmd, check=True)
        print(f"Time-lapse video saved as {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to merge chunks: {e}")
    finally:
        # Clean up
        for chunk_file in chunk_output_files:
            chunk_file.unlink()
        chunks_list_file.unlink()

def upload_to_nas(local_file, remote_dir):
    remote_path = f"{os.getenv('MOUNT_POINT')}/{remote_dir}/{Path(local_file).name}"
    try:
        shutil.copy(local_file, remote_path)
        print(f"Uploaded {local_file} to NAS at {remote_path}")
    except Exception as e:
        print(f"Failed to upload file: {e}")

if __name__ == "__main__":
    # Load configuration from environment variables
    tailscale_ip = os.getenv('TAILSCALE_IP')
    share_name = os.getenv('SHARE_NAME')
    mount_point = os.getenv('MOUNT_POINT')
    username = os.getenv('USERNAME')
    password = os.getenv('PASSWORD')
    source_directory_base = os.getenv('SOURCE_DIRECTORY_BASE')
    source_directories = os.getenv('SOURCE_DIRECTORIES').split(',')
    timelapse_output_dir = os.getenv('TIMELAPSE_OUTPUT_DIR')
    upload_path = os.getenv('UPLOAD_PATH')

    # Process date
    date = (datetime.now().date() - timedelta(days=1)).strftime("%Y%m%d")

    # Mount the SMB share
    mount_smb_share(
        tailscale_ip=tailscale_ip,
        share_name=share_name,
        mount_point=mount_point,
        username=username,
        password=password
    )

    for directory in source_directories:
        source_directory = f"{mount_point}{source_directory_base}/{directory}/{date}"
        label = directory_labels.get(directory, directory)
        timelapse_output = f"{timelapse_output_dir}/timelapse_{label}_{date}.mp4"

        create_time_lapse_parallel(
            source_dir=source_directory,
            output_file=timelapse_output,
            speed=60
        )
        upload_to_nas(local_file=timelapse_output, remote_dir=upload_path)