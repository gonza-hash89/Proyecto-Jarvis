═══════════════════════════════════════
FASE 2 — AUTONOMÍA (Mes 2)
═══════════════════════════════════════

Objetivo: Jarvis actúa sin que le pidas

1. brain/planner.py — Planificador multi-paso:
   - Descomponer "organiza mi semana" en subtareas
   - Ejecutar subtareas en orden lógico
   - Reportar progreso en cada paso
   - Manejar fallos parciales

2. brain/proactive.py — Motor proactivo:
   - Monitorear en background (hilo daemon)
   - Detectar patrones: "siempre me pides el clima 
     a las 8am" → decírtelo antes
   - Recordatorios automáticos antes de vencer
   - Alertas de cripto si precio cambia >5%

3. Coordinación entre agentes:
   - Agentes pueden llamarse entre sí via EventBus
   - WebAgent puede alimentar a DialogAgent
   - FileAgent puede coordinarse con CalendarAgent
   - Sin que el orquestador intermedie cada paso

Métricas: Jarvis completa tareas de 3+ pasos solo

═══════════════════════════════════════
FASE 3 — INDEPENDENCIA (Mes 3)
═══════════════════════════════════════

Objetivo: Jarvis funciona sin internet

1. Modelo local con Ollama:
   - Instalar Ollama en Windows
   - Modelo: llama3.2:3b (ligero, 2GB RAM)
   - Reemplaza Gemini cuando no hay internet
   - brain/local_llm.py: wrapper con misma interfaz

2. Embeddings locales:
   - sentence-transformers (modelo pequeño)
   - Búsqueda semántica en memoria: "lo que me dijiste 
     sobre mi trabajo" encuentra conversaciones relevantes
   - brain/semantic_search.py

3. Reentrenamiento del clasificador:
   - Cada semana: reentrenar LinearSVC con datos reales
   - brain/retrainer.py: job periódico automático
   - Mejora continua sin intervención manual

Métricas: 0 llamadas a APIs externas en modo offline

═══════════════════════════════════════
FASE 4 — PRESENCIA COMPLETA (Mes 4)
═══════════════════════════════════════

Objetivo: Dashboard tipo Mission Control

1. html/dashboard.html:
   - Panel izquierdo: esfera visual + estado
   - Panel central: conversación con historial
   - Panel derecho: agentes activos + métricas
   - Fondo oscuro, estética Iron Man

2. html/components/:
   - agents_panel.js: estado de cada agente
   - memory_panel.js: últimas memorias y facts
   - metrics_panel.js: tests, uptime, respuestas
   - conversation_panel.js: historial visual

3. WebSocket bidireccional:
   - Jarvis → Dashboard: eventos en tiempo real
   - Dashboard → Jarvis: comandos desde la UI
   - Control manual de agentes desde el panel

Métricas: Dashboard operativo con datos reales

═══════════════════════════════════════
FASE 5 — AGI PERSONAL (Mes 5-6)
═══════════════════════════════════════

Objetivo: Jarvis es tu socio, no tu herramienta

1. N5 Aprendizaje continuo:
   - Feedback loop: 👍/👎 después de cada respuesta
   - Correcciones que persisten: "no, quise decir X"
   - Reentrenamiento automático semanal
   - Embeddings para memoria semántica profunda

2. Multi-instancia:
   - Jarvis en PC + Jarvis en móvil sincronizados
   - Memoria compartida via API REST simple
   - Mismo estado, diferentes interfaces

3. Hardware dedicado (opcional):
   - Guía para migrar a Mac Mini M4
   - Docker container para portabilidad
   - Backup automático de memoria y modelos

4. Personalidad consistente:
   - Nombre personalizable (ya existe)
   - Tono adaptable (formal/casual según contexto)
   - Historia compartida: "¿recuerdas cuando...?"
   - Referencia a conversaciones antiguas naturalmente

═══════════════════════════════════════
MÉTRICAS GLOBALES DEL PROYECTO
═══════════════════════════════════════

Estado actual:
- Archivos Python: 45+
- Líneas de código: 15,000+
- Tests: 329 verdes
- Agentes: 10
- Intenciones: 52 (ES/EN)
- Consciencia: N0-N2 completo, N3-N4 en progreso

Meta final:
- Agentes: 15+
- Intenciones: 80+
- Tests: 500+
- Consciencia: N0-N5 completo
- Funciona offline al 80%
- Dashboard operativo
- Aprendizaje continuo activo

DECLARACIÓN DE HONESTIDAD:
Este sistema implementa simulación funcional de AGI.
No hay consciencia subjetiva real. Cada capacidad
es determinista, testeable y explicable.
El objetivo es máxima utilidad práctica, no
marketing de "inteligencia general".
