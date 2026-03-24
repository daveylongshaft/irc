#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parity File Utility
Description: A script to create, verify, and repair files in a directory
             using Reed-Solomon error correction codes. It can recover
             from the loss or corruption of up to 2 files.
Author: Gemini
Version: 1.2.0
Dependencies: reedsolo (pip install reedsolo)
"""

import os
import sys
import argparse
import json
import hashlib
import shutil
import time

try:
    from reedsolo import RSCodec, ReedSolomonError
except ImportError:
    print("Error: 'reedsolo' library not found.", file=sys.stderr)
    print("Please install it using: pip install reedsolo", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
PARITY_FILENAME = ".parity_set"
REDUNDANCY = 2  # Number of files that can be recovered
BLOCK_SIZE = 4096  # 4KB block size for processing files
METADATA_HEADER_SIZE = 16  # Bytes to store the length of the JSON metadata


class ParityManager:
    """
    Manages the creation, verification, and repair of files using parity data.
    """

    def __init__(self, base_dir, recursion_level):
        self.base_dir = base_dir
        self.recursion_level = recursion_level
        self.parity_filepath = os.path.join(self.base_dir, PARITY_FILENAME)
        self.rsc = RSCodec(REDUNDANCY)

    def _scan_files(self):
        """
        Scans for files in the base directory according to the recursion level.
        Excludes the parity file itself and any backup parity files.
        """
        file_list = []
        start_level = self.base_dir.count(os.sep)

        for root, dirs, files in os.walk(self.base_dir, topdown=True):
            # --- Recursion Level Control ---
            current_level = root.count(os.sep) - start_level
            if self.recursion_level != 0 and current_level >= self.recursion_level:
                dirs[:] = []  # Prune directories beyond the specified level
                continue

            for filename in files:
                if filename == PARITY_FILENAME or filename.startswith(f"{PARITY_FILENAME}.bak_"):
                    continue
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, self.base_dir)
                file_list.append(relative_path)

        file_list.sort()  # Ensure consistent file order
        return file_list

    def _hash_file(self, filepath):
        """Calculates the SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
            return None

    def _read_metadata(self):
        """Reads and returns the metadata from the parity file."""
        if not os.path.exists(self.parity_filepath):
            print("Parity file not found.", file=sys.stderr)
            return None
        try:
            with open(self.parity_filepath, 'rb') as f:
                metadata_len_bytes = f.read(METADATA_HEADER_SIZE)
                if not metadata_len_bytes:
                    print("Error: Parity file is empty or corrupt.", file=sys.stderr)
                    return None
                metadata_len = int.from_bytes(metadata_len_bytes, 'big')

                file_size = os.fstat(f.fileno()).st_size
                json_start_pos = file_size - metadata_len

                if json_start_pos < METADATA_HEADER_SIZE:
                    print("Error: Invalid metadata size or position in parity file.", file=sys.stderr)
                    return None

                f.seek(json_start_pos)
                metadata = json.loads(f.read(metadata_len).decode('utf-8'))
                return metadata
        except Exception as e:
            print(f"Error: Could not read metadata from parity file. It may be corrupt. {e}", file=sys.stderr)
            return None

    def _verify_integrity(self, metadata):
        """
        Verifies files against metadata and returns their status.
        Returns: (file_statuses, corrupted_or_missing_indices)
        """
        print("Verifying file integrity...")
        file_statuses = []
        corrupted_or_missing_indices = []

        for i, file_info in enumerate(metadata['files']):
            full_path = os.path.join(self.base_dir, file_info['path'])
            if not os.path.exists(full_path):
                print(f"  MISSING: {file_info['path']}")
                file_statuses.append('missing')
                corrupted_or_missing_indices.append(i)
            else:
                current_hash = self._hash_file(full_path)
                if current_hash != file_info['hash']:
                    print(f"  CORRUPT: {file_info['path']}")
                    file_statuses.append('corrupt')
                    corrupted_or_missing_indices.append(i)
                else:
                    print(f"  OK:      {file_info['path']}")
                    file_statuses.append('ok')

        return file_statuses, corrupted_or_missing_indices

    def create_parity_file(self, force_new=False, file_list=None):
        """
        Creates a new parity file for the files in the directory.
        If file_list is provided, it uses that list instead of scanning.
        """
        if os.path.exists(self.parity_filepath) and not force_new:
            print("Parity file already exists. Use -new to replace or -update to modify.")
            return

        if force_new and os.path.exists(self.parity_filepath):
            backup_path = f"{self.parity_filepath}.bak_{int(time.time())}"
            print(f"Backing up existing parity file to {backup_path}")
            shutil.move(self.parity_filepath, backup_path)

        if file_list is None:
            print("Scanning files...")
            files_to_protect = self._scan_files()
        else:
            print("Using provided file list...")
            files_to_protect = file_list

        if not files_to_protect:
            print("No files found to protect. Parity file not created.")
            return

        if len(files_to_protect) > (255 - REDUNDANCY):
            print(f"Error: Too many files ({len(files_to_protect)}). The current limit is {255 - REDUNDANCY}.")
            print("Reed-Solomon has a limit of 255 total data + parity shards.")
            return

        print(f"Found {len(files_to_protect)} files to protect.")
        metadata = {'block_size': BLOCK_SIZE, 'files': []}
        max_file_size = 0

        print("Analyzing files and calculating hashes...")
        for rel_path in files_to_protect:
            full_path = os.path.join(self.base_dir, rel_path)
            file_size = os.path.getsize(full_path)
            if file_size > max_file_size:
                max_file_size = file_size
            metadata['files'].append({'path': rel_path, 'size': file_size, 'hash': self._hash_file(full_path)})

        num_blocks = (max_file_size + BLOCK_SIZE - 1) // BLOCK_SIZE
        metadata['num_blocks'] = num_blocks

        print(f"Creating parity data ({num_blocks} blocks)...")
        try:
            with open(self.parity_filepath, 'wb') as parity_file:
                parity_file.seek(METADATA_HEADER_SIZE)

                file_handles = [open(os.path.join(self.base_dir, f['path']), 'rb') for f in metadata['files']]

                for block_num in range(num_blocks):
                    if (block_num + 1) % 100 == 0: print(f"  Processing block {block_num + 1}/{num_blocks}...")

                    stripe = [fh.read(BLOCK_SIZE).ljust(BLOCK_SIZE, b'\0') for fh in file_handles]

                    transposed_stripe = [bytes(block[i] for block in stripe) for i in range(BLOCK_SIZE)]

                    transposed_parity = []
                    for byte_slice in transposed_stripe:
                        encoded = self.rsc.encode(byte_slice)
                        transposed_parity.append(encoded[len(byte_slice):])

                    if transposed_parity:
                        parity_blocks = [bytearray(BLOCK_SIZE) for _ in range(REDUNDANCY)]
                        for byte_idx in range(BLOCK_SIZE):
                            for parity_idx in range(REDUNDANCY):
                                parity_blocks[parity_idx][byte_idx] = transposed_parity[byte_idx][parity_idx]

                        for p_block in parity_blocks:
                            parity_file.write(p_block)

                for fh in file_handles: fh.close()

                metadata_json = json.dumps(metadata, indent=4).encode('utf-8')
                metadata_len = len(metadata_json)
                parity_file.write(metadata_json)

                parity_file.seek(0)
                parity_file.write(metadata_len.to_bytes(METADATA_HEADER_SIZE, 'big'))

            print(f"\nSuccessfully created parity file: {self.parity_filepath}")

        except Exception as e:
            print(f"\nAn error occurred during parity creation: {e}", file=sys.stderr)
            if os.path.exists(self.parity_filepath): os.remove(self.parity_filepath)

    def check_only(self):
        """Performs a check and reports the status without repairing."""
        metadata = self._read_metadata()
        if not metadata: return

        _, corrupted_or_missing_indices = self._verify_integrity(metadata)

        num_errors = len(corrupted_or_missing_indices)
        if num_errors == 0:
            print("\nVerification complete. All files are intact.")
        else:
            print(f"\nFound {num_errors} missing or corrupt file(s).")
            print("Run with the --repair command to fix.")

    def repair(self):
        """Verifies file integrity and repairs them if necessary and possible."""
        metadata = self._read_metadata()
        if not metadata: return

        file_statuses, corrupted_or_missing_indices = self._verify_integrity(metadata)

        num_errors = len(corrupted_or_missing_indices)
        if num_errors == 0:
            print("\nVerification complete. All files are intact. No repair needed.")
            return

        print(f"\nFound {num_errors} missing or corrupt file(s).")

        if num_errors > REDUNDANCY:
            print(
                f"Error: Cannot repair. {num_errors} errors found, but parity data can only recover {REDUNDANCY} file(s).",
                file=sys.stderr)
            return

        print("Starting repair process...")
        num_data_shards = len(metadata['files'])
        num_blocks = metadata['num_blocks']

        try:
            for i, file_info in enumerate(metadata['files']):
                if file_statuses[i] != 'ok':
                    full_path = os.path.join(self.base_dir, file_info['path'])
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'wb') as f: pass

            file_handles = [open(os.path.join(self.base_dir, f['path']), 'rb+') for f in metadata['files']]

            with open(self.parity_filepath, 'rb') as parity_file:
                parity_file.seek(METADATA_HEADER_SIZE)

                for block_num in range(num_blocks):
                    if (block_num + 1) % 100 == 0: print(f"  Reconstructing block {block_num + 1}/{num_blocks}...")

                    stripe = []
                    for idx in range(num_data_shards):
                        file_handles[idx].seek(block_num * BLOCK_SIZE)
                        stripe.append(file_handles[idx].read(BLOCK_SIZE).ljust(BLOCK_SIZE, b'\0'))
                    for _ in range(REDUNDANCY):
                        stripe.append(parity_file.read(BLOCK_SIZE))

                    transposed_stripe = [bytearray(block[i] for block in stripe) for i in range(BLOCK_SIZE)]

                    reconstructed_transposed = []
                    try:
                        for byte_slice in transposed_stripe:
                            decoded_slice, _ = self.rsc.decode(byte_slice, erase_pos=corrupted_or_missing_indices)
                            reconstructed_transposed.append(decoded_slice)
                    except ReedSolomonError as e:
                        print(f"\nCritical Error: Could not decode block {block_num}. File repair failed. {e}",
                              file=sys.stderr)
                        for fh in file_handles: fh.close()
                        return

                    decoded_blocks = [bytearray(BLOCK_SIZE) for _ in range(num_data_shards)]
                    for byte_idx in range(BLOCK_SIZE):
                        for shard_idx in range(num_data_shards):
                            decoded_blocks[shard_idx][byte_idx] = reconstructed_transposed[byte_idx][shard_idx]

                    for idx in corrupted_or_missing_indices:
                        file_handles[idx].seek(block_num * BLOCK_SIZE)
                        file_handles[idx].write(decoded_blocks[idx])

            for i, fh in enumerate(file_handles):
                if i in corrupted_or_missing_indices: fh.truncate(metadata['files'][i]['size'])
                fh.close()

            print("\nRepair complete. Verifying repaired files...")
            all_repaired = True
            for idx in corrupted_or_missing_indices:
                file_info = metadata['files'][idx]
                full_path = os.path.join(self.base_dir, file_info['path'])
                new_hash = self._hash_file(full_path)
                if new_hash == file_info['hash']:
                    print(f"  SUCCESS: {file_info['path']} restored.")
                else:
                    print(f"  FAILURE: {file_info['path']} could not be verified after repair.", file=sys.stderr)
                    all_repaired = False

            if all_repaired: print("\nAll files successfully repaired and verified.")

        except Exception as e:
            print(f"\nAn error occurred during repair: {e}", file=sys.stderr)

    def update(self):
        """Checks for new/removed files and updates the parity set."""
        print("Checking for updates...")
        metadata = self._read_metadata()
        if not metadata:
            print("No parity file to update. Use --new to create one.")
            return

        _, corrupted_or_missing_indices = self._verify_integrity(metadata)
        if len(corrupted_or_missing_indices) > 0:
            print("\nFound corrupt or missing files. Please run --repair first before updating.", file=sys.stderr)
            return

        print("\nExisting files are intact. Scanning for changes...")

        current_files = set(self._scan_files())
        tracked_files = set([f['path'] for f in metadata['files']])

        new_files = current_files - tracked_files
        removed_files = tracked_files - current_files

        if not new_files and not removed_files:
            print("No changes detected. Parity file is already up to date.")
            return

        if new_files:
            print("New files found:")
            for f in sorted(list(new_files)): print(f"  + {f}")
        if removed_files:
            print("Removed files detected:")
            for f in sorted(list(removed_files)): print(f"  - {f}")

        print("\nRebuilding parity file to include changes...")
        self.create_parity_file(force_new=True, file_list=sorted(list(current_files)))


def main():
    """Main function to parse arguments and execute commands."""
    parser = argparse.ArgumentParser(
        description="Create, check, and repair files using parity data.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-n', '--new', action='store_true',
                       help='Force creation of a new parity file. Backs up the old one.')
    group.add_argument('-u', '--update', action='store_true', help='Update parity file with new or removed files.')
    group.add_argument('-c', '--check', action='store_true',
                       help='Check file integrity without repairing (default action).')
    group.add_argument('--repair', action='store_true', help='Check and repair corrupt or missing files.')

    parser.add_argument(
        '-r', '--recursion', type=int, nargs='?', const=0, default=1,
        help='Recurse into subdirectories.\n'
             'No value or 0: full recursion.\n'
             'N: recurse N levels deep (1 is current dir only).\n'
             'Default is 1 (current directory only).'
    )

    args = parser.parse_args()

    current_dir = os.getcwd()
    print(f"Operating in: {current_dir}")
    print(f"Recursion level set to: {'Full' if args.recursion == 0 else args.recursion}")

    manager = ParityManager(current_dir, args.recursion)

    if args.new:
        manager.create_parity_file(force_new=True)
    elif args.update:
        manager.update()
    elif args.repair:
        manager.repair()
    elif args.check:
        manager.check_only()
    else:
        # Default behavior
        if not os.path.exists(manager.parity_filepath):
            print("No parity file found. Creating a new one.")
            manager.create_parity_file()
        else:
            print("Parity file found. Checking file integrity (default action).")
            manager.check_only()

    # Wait for user input before exiting
    #input("\nPress Enter to exit...")

if __name__ == '__main__':
    main()
