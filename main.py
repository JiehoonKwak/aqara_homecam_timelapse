import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import shutil

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

def create_time_lapse_from_files(source_dir, output_file, speed=60):
    source_path = Path(source_dir).resolve()
    output_path = Path(output_file).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mp4_files = sorted(source_path.glob('*.mp4'))
    if not mp4_files:
        print("No MP4 files found to process.")
        return

    list_file_path = source_path / 'files.txt'
    with open(list_file_path, 'w') as f:
        for mp4 in mp4_files:
            f.write(f"file '{mp4}'\n")

    timelapse_cmd = [
        'ffmpeg',
        '-hwaccel', 'videotoolbox',  # Use hardware acceleration
        '-f', 'concat',
        '-safe', '0',
        '-i', str(list_file_path),
        '-filter:v', f"setpts=PTS/{speed}",
        '-c:v', 'h264_videotoolbox',
        '-b:v', '2M',  # Set target bitrate to control file size
        '-preset', 'fast',  # Speed up encoding
        '-pix_fmt', 'yuv420p',
        '-an',  # Disable audio
        str(output_path)
    ]

    try:
        subprocess.run(timelapse_cmd, check=True)
        print(f"Time-lapse video saved as {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to create time-lapse: {e}")
    finally:
        list_file_path.unlink()

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

    # Process date : 2일전꺼를 processing (time zone이 맞지를 않음)
    date = (datetime.now().date() - timedelta(days=2)).strftime("%Y%m%d")

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

        create_time_lapse_from_files(
            source_dir=source_directory,
            output_file=timelapse_output,
            speed=60
        )
        upload_to_nas(local_file=timelapse_output, remote_dir=upload_path)