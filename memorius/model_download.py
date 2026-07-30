"""ONNX model download utility for memorius.

Downloads the all-MiniLM-L6-v2 ONNX model for ChromaDB's default embedding function.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tarfile
from pathlib import Path
from typing import Callable, Optional

import httpx

# Model configuration
MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
MODEL_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
EXTRACTED_FOLDER_NAME = "onnx"
ARCHIVE_FILENAME = "onnx.tar.gz"

# Default cache directory
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "memorius" / "onnx_models"


def get_model_cache_dir() -> Path:
    """Get the model cache directory from env var or default."""
    env_dir = os.environ.get("MEMORIUS_MODEL_CACHE_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_CACHE_DIR


def get_model_path() -> Path:
    """Get the path to the extracted ONNX model."""
    cache_dir = get_model_cache_dir()
    return cache_dir / MODEL_NAME / EXTRACTED_FOLDER_NAME


def is_model_downloaded() -> bool:
    """Check if the ONNX model is already downloaded."""
    model_path = get_model_path()
    onnx_file = model_path / "model.onnx"
    return onnx_file.exists()


def _verify_sha256(file_path: Path, expected_hash: str) -> bool:
    """Verify the SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == expected_hash


def download_model(
    force: bool = False,
    progress_callback: Optional[Callable] = None,
) -> Path:
    """Download the ONNX model if not already present.
    
    Args:
        force: If True, re-download even if model exists
        progress_callback: Optional callback for progress updates (bytes_downloaded, total_bytes)
    
    Returns:
        Path to the extracted model directory
        
    Raises:
        RuntimeError: If download or extraction fails
    """
    cache_dir = get_model_cache_dir()
    model_dir = cache_dir / MODEL_NAME
    archive_path = model_dir / ARCHIVE_FILENAME
    extracted_path = model_dir / EXTRACTED_FOLDER_NAME
    
    # Check if already downloaded
    if not force and is_model_downloaded():
        print(f"ONNX model already downloaded: {extracted_path}")
        return extracted_path
    
    # Create directories
    model_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading ONNX model ({MODEL_NAME})...")
    print(f"  URL: {MODEL_URL}")
    print(f"  Destination: {model_dir}")
    
    try:
        # Download with progress
        with httpx.stream("GET", MODEL_URL, timeout=None) as response:
            response.raise_for_status()
            total_bytes = int(response.headers.get("content-length", 0))
            
            downloaded = 0
            with open(archive_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_bytes)
                    elif total_bytes > 0:
                        percent = (downloaded / total_bytes) * 100
                        print(f"\r  Progress: {percent:.1f}% ({downloaded}/{total_bytes} bytes)", end="", flush=True)
            
            if total_bytes > 0:
                print()  # New line after progress
            
        print("Download complete. Verifying hash...")
        
        # Verify hash
        if not _verify_sha256(archive_path, MODEL_SHA256):
            raise RuntimeError(
                f"Hash verification failed. Expected: {MODEL_SHA256}\n"
                "The downloaded file may be corrupted. Please try again with --force."
            )
        
        print("Hash verified. Extracting...")
        
        # Extract
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=model_dir)
        
        # Clean up archive
        archive_path.unlink()
        
        # Verify extraction
        if not is_model_downloaded():
            raise RuntimeError(
                f"Extraction failed. Model file not found at: {extracted_path / 'model.onnx'}"
            )
        
        print(f"Model downloaded successfully: {extracted_path}")
        return extracted_path
        
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"Failed to download ONNX model: {e}\n"
            "Check your internet connection and try again."
        )
    except tarfile.TarError as e:
        raise RuntimeError(
            f"Failed to extract ONNX model: {e}\n"
            "The downloaded file may be corrupted. Please try again with --force."
        )
    finally:
        # Clean up partial downloads on failure
        if archive_path.exists() and not is_model_downloaded():
            archive_path.unlink()


def setup_model(force: bool = False) -> bool:
    """Setup the ONNX model. Returns True if successful."""
    try:
        download_model(force=force)
        return True
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # Allow running as a script for testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Download ONNX model for memorius")
    parser.add_argument("--force", action="store_true", help="Re-download even if model exists")
    parser.add_argument("--check", action="store_true", help="Check if model is downloaded")
    args = parser.parse_args()
    
    if args.check:
        if is_model_downloaded():
            print(f"Model is downloaded: {get_model_path()}")
            sys.exit(0)
        else:
            print("Model is not downloaded.")
            sys.exit(1)
    
    success = setup_model(force=args.force)
    sys.exit(0 if success else 1)
