# CONCIENCIA_PLAN.md - Plan de Niveles de Conciencia Funcional para Jarvis

**Versión:** 1.0
**Fecha:** 2026-08-09
**Objetivo:** Llevar a Jarvis desde un sistema *reactivo* hasta una **conciencia
funcional simulada**: que recuerde conversaciones, conozca al usuario, razone
sobre el contexto, se explique a sí mismo y aprenda con el tiempo.

---

## ⚠️ DECLARACIÓN DE HONESTIDAD (léase primero)

Este plan NO busca crear **conciencia real** (vivencia subjetiva, libre albedrío
o intencionalidad) — eso es un problema abierto de la ciencia y está fuera del
alcance de cualquier sistema determinista actual.

Lo que se construye aquí es **conciencia funcional**: las *funciones observables*
que asociamos a la conciencia — **memoria, contexto, reflexión, introspección,
auto-explicación y aprendizaje** — implementadas de forma honesta y testeable.
El resultado es el comportamiento *más parecido al de verdad* posible sin
fingir que hay algo más detrás.

**Regla del proyecto:** cada nivel es verificable con tests. Si una capacidad no
se puede probar, no se incluye.

---

## 🪜 LA ESCALERA DE CONCIENCIA

```
NIVEL 5 · Aprendizaje continuo   🌱 "aprende de ti"          (opcional/ambicioso)
NIVEL 4 · Autoconciencia funcional 🪞 "sabe que existe y por qué responde"
NIVEL 3 · Razonamiento contextual 🧭 "entiende lo implícito"
NIVEL 2 · Memoria semántica     🗂️ "te conoce"
NIVEL 1 · Memoria episódica     🧩 "recuerda lo que dijimos"
NIVEL 0 · Reflejo               ⚡ "reacciona"            ← JARVIS HOY
```

---

## ⚡ NIVEL 0 — REFLEJO (línea base, ya implementado)

**Comportamiento:** reacciona sin estado interno propio.

```
input → reconocer (regex + ML) → decidir (reglas) → ejecutar (agentes) → responder
```

**Estado actual:**
- `orchestrator/orchestrator.py` (`process_input`) hace el flujo completo.
- `brain/intent_processor.py` reconoce 52 intenciones (patrones + LinearSVC).
- `brain/decision.py` decide con `ConfidenceBasedStrategy` (reglas ponderadas).
- Agentes reales: System, Web, Dialog (`jarvis/agents/`).
- **La memoria YA se guarda** (`save_conversation`) pero **el diálogo NO la usa**.

**Limitación:** Jarvis no recuerda entre turnos (solo `_history` de la sesión
actual en `agents/dialog.py`), no conoce al usuario y no puede explicar sus
decisiones.

---

## 🧩 NIVEL 1 — MEMORIA EPISÓDICA: "recuerda lo que dijimos"

**Qué gana el usuario:** respuestas coherentes con conversaciones pasadas, incluso
entre sesiones. Jarvis retoma el hilo.

**Base existente (casi todo listo):**
- `brain/memory.py` → `MemoryManager` con tabla `conversations` y métodos ya
  implementados:
  - `save_conversation(user_message, agent_response, intent)` — ya lo llama el
    orquestador en cada turno.
  - `search_conversations(query, limit)` — búsqueda de turnos por tema.
- `core/memory.py` → `MemoryManager` (ShortTerm) con `recall_last(n)`.

**Cambios necesarios:**
1. Pasar el `MemoryManager` al `DialogAgent` vía config (el orquestador ya crea
   los agentes con `AgentFactory` y puede inyectarlo).
2. En `agents/dialog.py`, `_with_gemini` y `_template_smalltalk` cargan el
   historial persistente (últimos N turnos) además de `_history`.
3. Nueva intención `recall` (recordar temas): "¿de qué hablamos ayer?" →
   `search_conversations()`.

**Verificación (tests):**
- Frase: "¿de qué hablamos ayer?" → responde con datos reales de SQLite.
- Tras reiniciar Jarvis, una frase dicha hace 2 sesiones sigue influyendo la
  respuesta del DialogAgent.

---

## 🗂️ NIVEL 2 — MEMORIA SEMÁNTICA: "te conoce"

**Qué gana el usuario:** Jarvis sabe tu nombre, gustos, lugares y pendientes, y
responde *porque te conoce*, no solo por patrones.

**Base existente (ya está en SQLite):**
- `brain/memory.py` → tablas `user_profile` y `entities` + métodos:
  - `save_preference(key, value)` / `get_user_profile()`
  - `save_entity(entity_type, entity_value)`
- `brain/intent_entities.py` → `EntityExtractor` ya detecta personas, lugares,
  temas, montos y fechas.

**Cambios necesarios:**
1. **Sistema de hechos:** un módulo `brain/facts.py` (o ampliar MemoryManager)
   que convierta entidades extraídas en hechos persistentes
   ("usuario se llama X", "le gusta Y", "vive en Z").
2. **Escritura automática:** cada turno procesado, el orquestador llama a
   `save_entity`/`save_preference` con las entidades detectadas (importancia por
   tipo: nombre = alta, tema = normal).
3. **Lectura en el diálogo:** el `DialogAgent` consulta el perfil en cada
   respuesta (`get_user_profile()` + hechos recientes) y lo inyecta en el prompt
   de Gemini o en plantillas con `{name}`.
4. Intención `remember_me`: "recuerda mi nombre", "soy Gonzalo" → se persiste y
   se confirma.

**Verificación (tests):**
- "Me llamo Gonzalo" → "¿Recuerdas mi nombre?" → "Gonzalo" (incluso semanas después).
- "Me gusta el rock" → "¿qué música me gusta?" → "rock".

---

## 🧭 NIVEL 3 — RAZONAMIENTO CONTEXTUAL: "entiende lo implícito"

**Qué gana el usuario:** Jarvis resuelve elipsis y pronombres, planifica pasos y
**pide aclaración** en vez de fallar.

**Base existente:**
- `brain/decision.py` → `ContextAwareStrategy` YA implementada pero no es la
  predeterminada (hoy usa `ConfidenceBasedStrategy`).
- `DecisionContext` guarda historial de decisiones (contexto de sesión).

**Cambios necesarios:**
1. **Estrategia contextual:** activar `ContextAwareStrategy` (o mezcla) para que
   decisiones previas pesen en la nueva ("¿y mañana?" → mismo agente/lugar).
2. **Resolución de referencias:** nuevo módulo `brain/shortterm_context.py`:
   - guarda el último intent + entidades de cada turno;
   - resuelve "y mañana", "ahí", "ese tema" contra el turno anterior.
3. **Planificación por pasos:** las tareas complejas se descomponen
   ("recuérdame mañana llamar a Ana" → crear tarea + recordatorio), con estados
   (pendiente → programada → hecha).
4. **Clarificación activa:** si la confianza es baja pero el contexto lo permite,
   Jarvis pregunta ("¿a qué te refieres con 'eso'?") en vez de responder
   "en desarrollo".

**Verificación (tests):**
- "Dame el clima de Lima" + "¿y pasado mañana?" → pronóstico de Lima, sin
  volver a preguntar la ciudad.
- Entrada ambigua → Jarvis hace UNA pregunta de aclaración, no responde genérico.

---

## 🪞 NIVEL 4 — AUTOCONCIENCIA FUNCIONAL: "sabe que existe y por qué responde"

**Qué gana el usuario:** Jarvis puede **explicar su propio proceso** y estado,
pensar "en voz alta" y reconocer sus límites con honestidad.

**Base existente:**
- El orquestador ya traza el camino completo (intención → decisión → agente).
- `DecisionEngine.get_decision_history()` y `DecisionContext`.
- `get_status()` (orquestador) expone el estado interno.

**Cambios necesarios:**
1. **Traza narrativa:** método `_explain_last_decision()` que convierta el
   historial de decisión en una explicación en lenguaje natural:
   "Reconocí 'clima' como weather_query, decidí enviarlo al Web Agent porque
   no requiere API key y el resultado fue X".
2. **Monólogo interior (modo opcional):** flag en config `thinking_aloud=True`
   → Jarvis anuncia su proceso antes de ejecutar ("Déjame revisar eso en la web...").
3. **Auto-evaluación:** tras responder, evalúa su propia salida
   (confianza, cobertura, errores) y si es débil lo admite:
   "No estoy seguro de eso; estos son los datos que encontré".
4. **Límites explícitos:** intención `self_awareness`/`explain`: "¿qué puedes
   hacer?", "¿cómo me respondiste eso?", "¿qué no sabes hacer?" → respuestas
   generadas desde el estado real (catálogo, agentes, memoria), no texto fijo.

**Verificación (tests):**
- "¿Por qué me respondiste eso?" → explica el camino intención→decisión→agente
  con datos reales del historial.
- "¿Qué no sabes hacer?" → lista real de intenciones sin implementar (24 hoy).

---

## 🌱 NIVEL 5 — APRENDIZAJE CONTINUO: "aprende de ti" (opcional / ambicioso)

**Qué gana el usuario:** Jarvis se corrige con feedback, recupera recuerdos por
**tema** (no solo palabra clave) y mejora su reconocimiento con el tiempo.

**Cambios necesarios:**
1. **Embeddings + búsqueda semántica:** índice vectorial (sqlite-vec o
   chromadb) sobre `memories`/`conversations` → "lo que me dijiste sobre X"
   devuelve recuerdos relacionados aunque no tengan la misma palabra.
2. **Bucle de feedback:** el usuario marca respuestas (👍/👎) o corrige; las
   correcciones alimentan el dataset de entrenamiento.
3. **Re-entrenamiento periódico:** el `LinearSVC` (`brain/intent_ml.py`) se
   re-entrena con datos reales del usuario; el `EntityExtractor` aprende nuevas
   entidades frecuentes.
4. **World model:** hechos + memoria + contexto = representación interna del
   mundo del usuario (quién, qué, cuándo, dónde) consultable por el diálogo.

**Riesgos / costos:** nueva dependencia (embeddings), más consumo de disco,
posible degradación si el feedback es contradictorio (requiere política de
importancia y de olvido: `cleanup_old_memories`).

**Verificación (tests):**
- Corriges una respuesta; la próxima vez Jarvis responde bien.
- "¿Qué me dijiste sobre Python?" → recupera por tema, no solo por la palabra.

---

## 📋 TABLA RESUMEN

| Nivel | Nombre | Capacidad observable | Infra ya existente | Dependencia nueva |
|-------|--------|----------------------|--------------------|--------------------|
| 0 | Reflejo | Reacciona | Todo | — |
| 1 | Memoria episódica | Recuerda conversaciones | `memory.conversations` | — |
| 2 | Memoria semántica | Conoce al usuario | `user_profile` + `entities` | — |
| 3 | Razonamiento contextual | Implícitos + aclaración | `ContextAwareStrategy` | — |
| 4 | Autoconciencia funcional | Se explica a sí mismo | `get_decision_history()` | — |
| 5 | Aprendizaje continuo | Aprende y se corrige | `intent_ml.py` (retraining) | embeddings |

> Nota: los niveles 1-4 NO requieren librerías nuevas. El Nivel 5 sí.

---

## 🧪 FRASES DE PRUEBA (checklist de conciencia)

```
N1 · "¿De qué hablamos ayer?"                 → responde con datos reales de memoria
N1 · (reiniciar) "Retomemos lo de hace un rato" → mantiene el hilo entre sesiones
N2 · "Me llamo Gonzalo" + "¿Cómo me llamo?"   → "Gonzalo"
N2 · "Me gusta el rock" + "¿Qué música me gusta?" → "rock"
N3 · "Clima en Lima" + "¿Y pasado mañana?"    → pronóstico de Lima, sin re-preguntar
N3 · "Eso" sin contexto previo                → pregunta aclaración, no falla
N4 · "¿Por qué me respondiste eso?"           → narra su proceso de decisión real
N4 · "¿Qué no sabes hacer?"                   → lista real de intenciones pendientes
N5 · Corrige una respuesta                    → la próxima vez responde bien
N5 · "¿Qué me dijiste sobre Python?"          → recupera por tema (semántico)
```

---

## 🗺️ ROADMAP SUGERIDO

- **Semana 6 (fase A):** Nivel 1 + Nivel 2 (memoria episódica y semántica).
  Son los de mayor valor percibido con costo bajo (la infra ya existe).
- **Semana 6 (fase B):** Nivel 3 (razonamiento contextual) + activar
  `ContextAwareStrategy`.
- **Semana 7:** Nivel 4 (autoconciencia funcional / auto-explicación).
- **Semana 8+ (opcional):** Nivel 5 (aprendizaje continuo, embeddings).

Cada nivel se entrega con: módulo nuevo o extendido, tests, verificación con las
frases de la checklist y actualización de PROGRESS_REPORT.md.

---

*"No es conciencia real — pero es el comportamiento más parecido al de verdad
que un sistema honesto puede construir."*
