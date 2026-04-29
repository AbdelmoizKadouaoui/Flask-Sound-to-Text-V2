from pathlib import Path
from zipfile import ZipFile
import urllib.request

from config import DOWNLOADS_DIR, MODELS_DIR, VOSK_MODELS


def download_file(url: str, destination: Path) -> None:
    print(f"Téléchargement depuis: {url}")
    print(f"Vers: {destination}")

    def progress(block_num, block_size, total_size):
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        percent = min(downloaded * 100 / total_size, 100)
        print(f"\rTéléchargement: {percent:.1f}%", end="")

    urllib.request.urlretrieve(url, destination, progress)
    print("\nTéléchargement terminé.")


def extract_zip(zip_path: Path, extract_to: Path) -> None:
    print("Extraction...")
    with ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_to)
    print("Extraction terminée.")


def download_and_extract_model(key: str, info: dict) -> None:
    final_model_path = MODELS_DIR / info["folder"]
    zip_path = DOWNLOADS_DIR / f"{info['folder']}.zip"

    print("\n" + "=" * 70)
    print(f"Modèle: {info['label']}")
    print("=" * 70)

    if final_model_path.exists():
        print(f"Déjà installé, ignoré: {final_model_path}")
        return

    if not zip_path.exists():
        download_file(info["url"], zip_path)
    else:
        print(f"ZIP déjà présent, téléchargement ignoré: {zip_path}")

    extract_zip(zip_path, MODELS_DIR)

    if final_model_path.exists():
        print(f"OK: {final_model_path}")
    else:
        print("ATTENTION: extraction terminée mais le dossier attendu n'a pas été trouvé.")
        print(f"Dossier attendu: {final_model_path}")


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print("Téléchargement automatique de tous les modèles Vosk...")
    print(f"Dossier models: {MODELS_DIR}")

    for key, info in VOSK_MODELS.items():
        try:
            download_and_extract_model(key, info)
        except Exception as error:
            print("\nERREUR pendant le téléchargement/extraction.")
            print(f"Modèle: {info['label']}")
            print(f"Détail: {error}")

    print("\nTerminé.")


if __name__ == "__main__":
    main()
