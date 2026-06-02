# Используем официальный Python образ
FROM python:3.11-slim

# Установим рабочую директорию
WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt .

# Установим зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Запускаем бота
CMD ["python", "main.py"]
