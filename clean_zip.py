import os
import zipfile

zip_name = 'ShadowBroker_v0.3.zip'

if os.path.exists(zip_name):
    try:
        os.remove(zip_name)
    except Exception as e:
        print(f"Failed to delete old zip: {e}")

def add_dir(zipf, dir_path, excludes):
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in excludes]
        for f in files:
            file_path = os.path.join(root, f)
            zipf.write(file_path, arcname=file_path)

try:
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        print("Zipping backend...")
        add_dir(zipf, 'backend', {'venv', '__pycache__'})
        
        print("Zipping frontend...")
        add_dir(zipf, 'frontend', {'node_modules', '.next'})
        
        print("Zipping root files...")
        zipf.write('docker-compose.yml')
        zipf.write('start.bat')
        zipf.write('start.sh')
        zipf.write('README.md')

    final_size = os.path.getsize(zip_name) / (1024 * 1024)
    print(f"\n✅ SUCCESS! Created {zip_name}. Final size: {final_size:.2f} MB")

except Exception as e:
    print(f"\n❌ ERROR creating zip: {e}")
