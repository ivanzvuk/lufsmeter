"""
Создание иконок для macOS (.icns) и Windows (.ico).

Требования:
  pip install Pillow

Для macOS потребуется дополнительно iconutil (встроен в macOS):
  python create_icon_mac.py
"""
import sys
from PIL import Image, ImageDraw
import subprocess
import os
import tempfile
import shutil


def create_png_icon(size, filepath):
    """Создает PNG иконку заданного размера"""
    img = Image.new('RGB', (size, size), color='#2b2b2b')
    draw = ImageDraw.Draw(img)

    margin = size // 8
    bar_width = max(2, size // 12)
    max_height = size - margin * 2

    bars = [
        (margin, int(max_height * 0.5), '#00ff00'),
        (margin + bar_width + 2, int(max_height * 0.3), '#00ff00'),
        (margin + (bar_width + 2) * 2, int(max_height * 0.55), '#00ff00'),
        (margin + (bar_width + 2) * 3, int(max_height * 0.15), '#ff0000'),
        (margin + (bar_width + 2) * 4, int(max_height * 0.6), '#00ff00'),
        (margin + (bar_width + 2) * 5, int(max_height * 0.4), '#ffff00'),
    ]

    for x, h, color in bars:
        y0 = margin + max_height - h
        draw.rectangle([x, y0, x + bar_width, margin + max_height], fill=color)

    img.save(filepath, format='PNG')
    return filepath


def create_icns(png_path, output_path):
    """Создает .icns из PNG через iconset"""
    iconset_dir = tempfile.mkdtemp(suffix='.iconset')

    sizes = {
        'icon_16x16.png': 16,
        'icon_16x16@2x.png': 32,
        'icon_32x32.png': 32,
        'icon_32x32@2x.png': 64,
        'icon_128x128.png': 128,
        'icon_128x128@2x.png': 256,
        'icon_256x256.png': 256,
        'icon_256x256@2x.png': 512,
        'icon_512x512.png': 512,
        'icon_512x512@2x.png': 1024,
    }

    source = Image.open(png_path)

    for name, size in sizes.items():
        resized = source.resize((size, size), Image.LANCZOS)
        resized.save(os.path.join(iconset_dir, name), format='PNG')

    try:
        subprocess.run(
            ['iconutil', '-c', 'icns', iconset_dir, '-o', output_path],
            check=True, capture_output=True
        )
        print(f"Создан .icns: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка создания .icns: {e}")
        print("Убедитесь, что вы на macOS с установленным iconutil")
    finally:
        shutil.rmtree(iconset_dir)


def create_ico(png_path, output_path):
    """Создает .ico из PNG"""
    img = Image.open(png_path)
    img.save(output_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Создан .ico: {output_path}")


if __name__ == '__main__':
    tmp_png = 'app_icon_1024.png'
    create_png_icon(1024, tmp_png)

    if sys.platform == 'darwin':
        create_icns(tmp_png, 'icon.icns')
    
    create_ico(tmp_png, 'icon.ico')

    os.remove(tmp_png)
    print("Готово!")
