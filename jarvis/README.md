# 🤖 Jarvis - Asistente de Voz en Python

Un asistente de voz inteligente en español e inglés que puede realizar múltiples tareas.

## ✨ Características

- 🎤 Reconocimiento de voz en español
- 🔊 Síntesis de voz (text-to-speech)
- 🕐 Consultar hora y fecha
- 📚 Buscar información en Wikipedia
- 🎵 Reproducir música
- 🌐 Abrir navegadores (YouTube, Google)
- 📸 Tomar capturas de pantalla
- 😂 Contar chistes
- 🖥️ Control del sistema (apagar, reiniciar)
- 📝 Sistema de nombre personalizado
- 🧠 **Intent Recognizer HÍBRIDO** (regex + ML) con 52 intenciones bilingües ES/EN
- ⚡ Detección de idioma automática (es/en/mixed)
- 🎯 Extracción de entidades (montos, fechas, duraciones, personas, temas)
- 📋 Notas y tareas (`data/notas.md`, `data/tareas.txt`)
- ⏰ Temporizadores locales
- 📺 Streaming (Netflix/Prime/Disney/HBO), podcasts, noticias
- 🗺️ Mapas, rutas, tráfico, Uber, vuelos y hoteles
- 🌦️ Clima (buscador web)
- 🖥️ **System Agent**: apagar/reiniciar, apps, carpetas, captura, volumen, papelera
- 🌐 **Web Agent**: clima (Open-Meteo), cripto (CoinGecko), noticias, búsqueda, sin API keys
- 💬 **Dialog Agent**: chistes, traducción (MyMemory), ayuda, cambio de nombre, Gemini opcional
- 📁 **File Agent**: notas, tareas, recordatorios y archivos
- 📅 **Email/Calendar Agent**: IMAP + Google Calendar (degradación elegante)
- 🧠 **Memoria episódica (N1)**: recuerda conversaciones entre sesiones (SQLite)
- 🧠 **Memoria semántica (N2)**: recuerda hechos sobre ti (nombre, preferencias)
- 🧠 **Contexto a corto plazo (N3)**: resuelve elipsis/pronombres ("¿y pasado mañana?")
- 🪞 **Autoconciencia funcional (N4)**: explica por qué respondió, su estado, sus límites
  y su arquitectura, leyendo su estado real desde la memoria

## 🧠 Consciencia funcional N0-N4

| Nivel | Qué es | Estado |
|-------|--------|--------|
| **N0** | Reconocimiento híbrido (regex + ML), 52 intenciones bilingües | ✅ |
| **N1** | Memoria episódica: recall de conversaciones entre sesiones | ✅ |
| **N2** | Memoria semántica: hechos del usuario (nombre, preferencias) | ✅ |
| **N3** | Contexto a corto plazo: elipsis/pronombres del turno anterior | ✅ |
| **N4** | Autoconciencia funcional: introspección + auto-evaluación | ✅ |

Puedes preguntarle: *"¿por qué me respondiste eso?"*, *"¿cuál es tu estado?"*,
*"¿qué no sabes hacer?"* o *"¿cómo funcionas?"* — responde con datos reales
(última decisión, snapshot del sistema, catálogo de intenciones pendientes).

## ✅ Estado actual (Semana 7)

- **388 tests verdes** · 5 agentes reales · consciencia N0-N4 completa
- Proyecto al **64%** · lista para ejecutar en modo texto (voz opcional)

## 📦 Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/gonza-hash89/Proyecto-Jarvis.git
cd Proyecto-Jarvis/jarvis
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

**Nota importante:** En Windows, también necesitas instalar PyAudio:
```bash
pip install pipwin
pipwin install pyaudio
```

## 🚀 Uso

```bash
python jarvis.py
```

### Comandos disponibles:

| Comando | Función |
|---------|----------|
| "hora" | Dice la hora actual |
| "fecha" | Dice la fecha actual |
| "wikipedia [tema]" | Busca en Wikipedia |
| "reproducir música" | Reproduce una canción |
| "pon música" | Reproduce una canción |
| "abrir youtube" | Abre YouTube |
| "abrir google" | Abre Google |
| "cambia tu nombre" | Cambia el nombre de Jarvis |
| "captura de pantalla" | Toma una screenshot |
| "cuéntame un chiste" | Cuenta un chiste |
| "apagar" | Apaga el sistema |
| "reiniciar" | Reinicia el sistema |
| "desconectar" o "salir" | Cierra Jarvis |

## 🔧 Mejoras implementadas

✅ **Ahora Jarvis habla en TODOS los comandos**
✅ **Mejor manejo de errores**
✅ **Docstrings en todas las funciones**
✅ **Archivo requirements.txt para fácil instalación**
✅ **Respuestas más naturales**

## ⚙️ Configuración

### Cambiar voz (Masculina/Femenina):
En `jarvis.py`, línea 10:
```python
engine.setProperty('voice', voices[1].id)  # 1 = Femenina, 0 = Masculina
```

### Cambiar velocidad del habla:
```python
engine.setProperty('rate', 150)  # Velocidad (0-300)
```

### Cambiar volumen:
```python
engine.setProperty('volume', 1)  # Volumen (0-1)
```

## 🐛 Solución de problemas

### "No se escucha el micrófono"
- Verifica que tu micrófono esté conectado
- Comprueba los permisos de micrófono en Windows

### "Error con PyAudio"
```bash
pipwin install pyaudio
```

### "No reconoce comandos"
- Habla claro y lentamente
- Asegúrate de estar en un lugar sin mucho ruido

## 📝 Notas

- El nombre de Jarvis se guarda en `assistant_name.txt`
- Las capturas se guardan en `Documentos/Pictures/captura.png`
- Requiere conexión a internet para Wikipedia y reconocimiento de voz

## 🚀 Próximas mejoras

- [ ] Cerrar las ~22 intenciones del catálogo aún "en desarrollo"
- [ ] Integración con WhatsApp
- [ ] Automatización de tareas (multi-acción)
- [ ] Control de voz continuo + wake word
- [ ] Interfaz gráfica

## 👨‍💻 Autor

**gonza-hash89** - 2026

## 📄 Licencia

Este proyecto está bajo licencia libre.
