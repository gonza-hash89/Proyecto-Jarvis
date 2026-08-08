# WEEK5_TASKS.md - Verificación SEMANA 5: Agentes Esenciales

**Fecha de cierre:** 2026-08-08
**Objetivo:** 3 agentes reales (System, Web, Dialog) integrados en el orquestador,
con degradación elegante, tests y cobertura ≥90%.
**Decisiones aprobadas:**
- ✅ Stack completo: agentes en `jarvis/agents/` sobre `core/agent_base.Agent`
- ✅ Todos los imports opcionales (requests, wikipedia, feedparser, pyjokes, genai,
     pyautogui, pycaw) con degradación elegante y mockeables en tests
- ✅ FILE Agent y CREATIVE Agent → movidos a SEMANA 6
- ✅ Fase 5 = SOLO tests, documentación y verificación (sin tocar agentes ni orquestador)

---

## FASE 0 — FRAMEWORK DE AGENTES (Lunes)

- [x] `agents/base.py`: AgentBase con ciclo de vida (initialize/cleanup/stop),
      get_info(), logging automático y record_error/_safe_call
- [x] `agents/registry.py`: register/get/list/list_all/start_all/stop_all/clear
- [x] `agents/factory.py`: AgentFactory con `_AGENT_MAP` (SYSTEM/WEB/DIALOG) y
      degradación elegante (None sin crashear)
- [x] Criterio: agentes concretos aceptan `(agent_type, config)` y llaman a super()

## FASE 1 — SYSTEM AGENT (Martes)

- [x] `system_control`: apagar/reiniciar/bloquear/dormir (os.system, Windows real)
- [x] `open_application`: 13 web (webbrowser) + 9 locales (os.startfile)
- [x] `open_folder`: Explorador con os.path.expanduser
- [x] `take_screenshot`: pyautogui → PNG en ~/Pictures (sin pyautogui → informativo)
- [x] `volume_control`: pycaw opcional (sin pycaw → "en desarrollo")
- [x] `empty_trash`: Clear-RecycleBin vía PowerShell (timeout 30s)
- [x] `lock_session`: LockWorkStation
- [x] Smart fallback: procesos (tasklist/taskkill) + intenciones "en desarrollo"
- [x] Tests: `test_system_agent.py` (21 + cobertura extra)

## FASE 2 — WEB AGENT (Miércoles)

- [x] `weather_query`: Open-Meteo real (geocoding + pronóstico) con WMO → español
- [x] `crypto_price`: CoinGecko real (USD + variación 24h), 23 monedas/alias
- [x] `search_info`: Wikipedia → DuckDuckGo HTML → Google (3 niveles)
- [x] `news_query`: Google News RSS vía feedparser (opcional)
- [x] `get_exchange_rate` / `check_investments`: fallback elegante a Google
- [x] Tests: `test_web_agent.py` (24) + cobertura 92%

## FASE 3 — DIALOG AGENT (Jueves)

- [x] `tell_joke`: Gemini → pyjokes(es) → plantilla fija (3 niveles de degradación)
- [x] `change_name`: persistido en `jarvis/data/assistant_name.txt`
- [x] `help_query`: manual generado desde INTENT_CATALOG (52 comandos agrupados)
- [x] `smalltalk`: 7 reglas + keywords con `{name}` sustituible
- [x] `translate_text`: MyMemory API gratuita (sin key)
- [x] MODO GEMINI: contexto de sesión (últimas 5 interacciones), sin exponer la key
- [x] Tests: `test_dialog_agent.py` (26) + cobertura 98%

## FASE 4 — INTEGRACIÓN ORCHESTRATOR (Viernes-Sábado)

- [x] `_AGENT_ROUTING`: 12 intenciones → agentes (web 5, system 4, dialog 3)
- [x] `_execute_intent`: agent.process() → respuesta; fallback a 23 acciones directas
- [x] `_find_agent_for` + `_agent_handles`: solo delega si el agente registra el handler
- [x] `_agent_message` / `_agent_response_text`: contrato estándar agente ↔ orquestador
- [x] 3 agentes creados con AgentFactory e inicializados (start_all) al arrancar
- [x] Tests: `test_orchestrator_agents.py` (10)

## FASE 5 — TESTS Y CIERRE (Domingo)

- [x] 70 tests nuevos: `test_agents_framework.py` (29), `test_semana5_coverage.py` (32),
      `test_week5_smoke.py` (8)
- [x] Smoke test E2E vía `process_input()` con agentes reales y mocks de red/OS:
      clima en Lima, precio del bitcoin, abre google, apaga el equipo, chiste, ayuda
- [x] Suite completa: `python -m pytest jarvis/tests -q` → **227 passed**
- [x] Cobertura: `--cov=jarvis/agents` → **TOTAL 97%**
      (system 99%, dialog 98%, web 92%, base/factory/registry 100%)
- [x] Documentación: PROGRESS_REPORT.md actualizado + WEEK5_TASKS.md
- [x] Commit final `✅ Semana 5 COMPLETA: 3 agentes reales, 33+ intenciones, 157+ tests`
      y push a origin/main

---

## RESUMEN DE ENTREGABLES

| Entregable | Estado |
|-----------|--------|
| `agents/base.py` | ✅ |
| `agents/registry.py` | ✅ |
| `agents/factory.py` | ✅ |
| `agents/system.py` | ✅ 391 líneas |
| `agents/web.py` | ✅ 477 líneas |
| `agents/dialog.py` | ✅ 466 líneas |
| Orquestador delega en agentes | ✅ |
| Tests totales | ✅ 227 |
| Cobertura jarvis/agents | ✅ 97% |
| Intenciones reales | ✅ 33 (24 pendientes → S6) |
