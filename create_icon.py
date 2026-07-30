"""
Создание icon.ico для Windows.
Используется только на Windows; на macOS используйте create_icon_mac.py.
"""
from PIL import Image, ImageDraw
import sys

# Создаем простую иконку 64x64
img = Image.new('RGB', (64, 64), color='#2b2b2b')
draw = ImageDraw.Draw(img)

# Рисуем волну
draw.rectangle([16, 20, 20, 44], fill='#00ff00')  # Зеленая полоса
draw.rectangle([24, 15, 28, 44], fill='#00ff00')  # Зеленая полоса  
draw.rectangle([32, 25, 36, 44], fill='#00ff00')  # Зеленая полоса
draw.rectangle([40, 10, 44, 44], fill='#ff0000')  # Красная полоса
draw.rectangle([48, 30, 52, 44], fill='#00ff00')  # Зеленая полоса

# Сохраняем как ICO
img.save('icon.ico', format='ICO', sizes=[(64, 64)])

print("Иконка создана: icon.ico")