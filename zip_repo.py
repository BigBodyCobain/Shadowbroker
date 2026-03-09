import os
import zipfile

def create_clean_zip():
    zip_name = 'ShadowBroker_v0.3.zip'
    exclude_dirs = {'.git', 'node_modules', 'venv', '.next', '__pycache__'}
    exclude_files = {zip_name, 'zip_repo.py', '.env', '.env.local'}

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file in exclude_files:
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, '.')
                zipf.write(file_path, arcname)
    print(f"Created {zip_name} successfully!")

if __name__ == '__main__':
    create_clean_zip()
