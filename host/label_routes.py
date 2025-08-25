# host/label_routes.py
import os
from pathlib import Path
import shutil
import pathspec
from config import Config


def get_gitignore_spec(root_dir: Path) -> pathspec.PathSpec:
    """
    Read .gitignore file and create a PathSpec matcher.

    Args:
        root_dir: Project root directory containing .gitignore

    Returns:
        PathSpec object for matching ignored paths
    """
    gitignore_path = root_dir / '.gitignore'
    if not gitignore_path.exists():
        return pathspec.PathSpec([])
    with open(gitignore_path, 'r') as f:
        gitignore = f.read().splitlines()
    return pathspec.PathSpec.from_lines(
        pathspec.patterns.GitWildMatchPattern,
        gitignore
    )


def label_project_files(
        root_dir: Path,
        target_folders: list[str] = None,
        target_extensions: list[str] = None
) -> tuple[int, list[str]]:
    """
    Scan and label files in the project directory with their relative paths.
    Also copies files to a flat 'selection' directory with path-based names.
    Respects .gitignore patterns.
    Args:
        root_dir: Project root directory
        target_folders: List of top-level folders to scan
        target_extensions: List of file extensions to process

    Returns:
        tuple: (Number of files processed, List of files needing manual review)
    """
    if target_folders is None:
        target_folders = ['api', 'daemon', 'frontend', 'native']
    if target_extensions is None:
        target_extensions = ['.py', '.tsx', '.ts']
    files_processed = 0
    follow_up_list = []
    # Create selection directory
    selection_dir = Path(Config.TEST_GALLERY_DIR) / 'selection'
    if os.path.exists(selection_dir):
        shutil.rmtree(selection_dir)
    selection_dir.mkdir(parents=True)
    # Get gitignore matcher
    gitignore_spec = get_gitignore_spec(root_dir)
    # Process top-level files first
    for file_path in root_dir.glob('*'):
        if not file_path.is_file() or file_path.suffix not in target_extensions:
            continue
        relative_path = str(file_path.relative_to(root_dir))
        # Skip if path matches gitignore patterns
        if gitignore_spec.match_file(relative_path):
            continue
        # Copy file to selection directory with special prefix for top-level files
        flat_name = f".--{file_path.name}"
        selection_path = selection_dir / flat_name
        shutil.copy2(file_path, selection_path)
        # Process the file content (similar to folder processing)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.readlines()
        except UnicodeDecodeError:
            continue
        comment_char = '//' if file_path.suffix in ['.tsx', '.ts'] else '#'
        new_label = f"{comment_char} {relative_path}\n"
        # Remove any path-like comments in first 5 lines (except line 0)
        for i in range(1, min(5, len(content))):
            line = content[i]
            if (line.startswith('#') or line.startswith('//')) and line.count('/') >= 2:
                content.pop(i)
                break
        # Update or add the label
        if content and (content[0].startswith('#') or content[0].startswith('//')):
            content[0] = new_label
        else:
            content.insert(0, new_label)
        # Write updated content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(content)
        files_processed += 1
    # Process files in target folders
    for folder in target_folders:
        folder_path = root_dir / folder
        if not folder_path.exists():
            continue
        for file_path in folder_path.rglob('*'):
            if not file_path.is_file() or file_path.suffix not in target_extensions:
                continue
            relative_path = str(file_path.relative_to(root_dir)).replace('\\', '/')
            # Skip if path matches gitignore patterns
            if gitignore_spec.match_file(relative_path):
                continue
            comment_char = '//' if file_path.suffix in ['.tsx', '.ts'] else '#'
            new_label = f"{comment_char} {relative_path}\n"
            # Read existing content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.readlines()
            except UnicodeDecodeError:
                continue  # Skip binary files
            # Remove any path-like comments in first 5 lines (except line 0)
            for i in range(1, min(5, len(content))):
                line = content[i]
                if (line.startswith('#') or line.startswith('//')) and line.count('/') >= 2:
                    content.pop(i)
                    break
            # Update or add the label
            if content and (content[0].startswith('#') or content[0].startswith('//')):
                content[0] = new_label
            elif content:
                content.insert(0, new_label)
            # Write updated content
            if content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.writelines(content)
                # Copy file to selection directory with path-based name
                flat_name = relative_path.replace('/', '--')
                selection_path = selection_dir / flat_name
                shutil.copy2(file_path, selection_path)
            files_processed += 1
    return files_processed, follow_up_list


def organize_by_search_terms(selection_dir: Path, search_terms: list[str]) -> dict[str, list[str]]:
    """
    Organize files from the selection directory into subfolders based on search terms.
    Files are copied to subfolders if they contain any of the words in a search term.
    :param selection_dir: Directory containing the flattened project files
    :param search_terms: List of search terms (each term can contain multiple words)
    :return: Dictionary mapping search terms to lists of matching files
    """
    results = {}
    # Create normalized search terms (split multi-word terms)
    search_map = {term: term.lower().split() for term in search_terms}
    # Process each file
    for file_path in selection_dir.iterdir():
        if not file_path.is_file():
            continue
        try:
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().lower()
        except UnicodeDecodeError:
            continue
        # Check each search term
        for original_term, words in search_map.items():
            # Count total matches in this file for all words in the term
            match_count = sum(content.count(word) for word in words)
            if match_count > 0:
                # Create folder with original term if needed
                term_folder = selection_dir / original_term.replace(' ', '__')
                term_folder.mkdir(exist_ok=True)
                # Create new filename with match count prefix
                new_filename = f"{match_count:04d}_{file_path.name}"
                dest_path = term_folder / new_filename
                if not dest_path.exists():  # Avoid copying if already exists
                    shutil.copy2(file_path, dest_path)
                # Track results
                if original_term not in results:
                    results[original_term] = []
                results[original_term].append(new_filename)
    return results


def main(search_terms):
    project_dir = Path(Config.PROJECT_DIR)
    files_processed, follow_up_list = label_project_files(
        project_dir,
        target_folders=['core', 'tests'],
        target_extensions=['.py', '.tsx', '.ts']
    )
    print(f"Files processed: {files_processed}")
    print("\nFiles needing review:")
    for file in follow_up_list:
        print(f"- {file}")
    # Organize files by search terms
    if search_terms:
        selection_dir = Path(Config.TEST_GALLERY_DIR) / 'selection'
        search_results = organize_by_search_terms(selection_dir, search_terms)
        # Print results
        print("\nSearch organization results:")
        for term, files in search_results.items():
            print(f"\n{term} ({len(files)} files):")
            for file in sorted(files):
                print(f"  - {file}")


if __name__ == "__main__":
    # Define search terms for organizing files
    # Terms separated by spaces are ORed with each other
    default_search_terms = []
    print("\nStarting project labeling...")
    main(search_terms=default_search_terms)
    print('DONE!!')
