<!--
Sync Impact Report
- Version change: (plantilla sin completar) → 1.0.0
- Principios: 15 principios nuevos (1–15), definidos por el usuario; ninguno renombrado.
- Secciones agregadas: Core Principles (lista numerada de una línea por principio), Governance.
- Secciones eliminadas: [SECTION_2_NAME] y [SECTION_3_NAME] de la plantilla (el usuario pidió
  solo 15 principios, sin agregar otros; el detalle técnico vive en docs/architecture.md).
- Formato: los principios van como lista de una línea cada uno (en lugar de un encabezado ###
  por principio) para cumplir el límite de 15 líneas de principios pedido por el usuario.
- Plantillas dependientes: sin cambios (leen la constitución en tiempo de ejecución).
- TODOs diferidos: ninguno.
-->
# Live Subs Constitution

## Core Principles

1. **Stack**: Python 3.12, FastAPI, Redis y ffmpeg; el frontend es HTML + JS sin paso de build. Prohibido Node.
2. **IA**: el audio va solo por Gemini Live API en streaming y se traducen solo frases finales. Prohibido enviar audio por REST.
3. **Contrato**: todo evento entre componentes es un `SubtitleEvent` de `src/subs/common/schema.py`; un cambio incompatible sube `schema_version`.
4. **Configuración**: modelos, parámetros y escenarios viven en `.env`, `sessions.yaml` y glosarios. Ningún valor fijo en el código.
5. **Secretos**: ninguna credencial entra al repositorio; solo el worker recibe `GEMINI_API_KEY`.
6. **Aislamiento**: la falla de un escenario nunca detiene a otro.
7. **Latencia**: la ingesta nunca se bloquea, toda cola es acotada y toda latencia se mide.
8. **Prioridad**: no se empieza P1 sin P0 validado, ni P2 sin P1 validado.
9. **Spec primero**: ningún cambio de comportamiento entra al código sin actualizar antes la spec.
10. **Tests**: toda función pura tiene test con pytest; la integración se valida con los clips de `samples/`.
11. **Suite verde**: una tarea solo se marca hecha si `pytest` pasa.
12. **Despliegue**: `docker compose up` funciona siempre desde un clon limpio.
13. **Simplicidad**: ninguna dependencia nueva sin justificarla en el plan; gana la solución más simple que cumpla el requisito.
14. **Logs**: JSON con `session_id`; en nivel INFO no se registra audio ni texto de subtítulos.
15. **Idioma**: código, commits y README en inglés; documentos internos en español.

## Governance

- Esta constitución prevalece sobre cualquier otro documento; `docs/architecture.md` es la fuente de
  verdad del diseño y debe respetarla. Ante un conflicto entre documentos, se detiene el trabajo y se
  consulta al responsable del proyecto.
- Toda enmienda se hace con `/speckit-constitution`, requiere aprobación explícita del responsable y
  sube la versión con SemVer: MAJOR si elimina o redefine un principio, MINOR si agrega uno, PATCH si
  solo aclara la redacción.
- Cada plan verifica el cumplimiento en su "Constitution Check" y cada revisión de tarea confirma que
  no viola ningún principio; una excepción se justifica por escrito en el plan.

**Version**: 1.0.0 | **Ratified**: 2026-09-24 | **Last Amended**: 2026-09-24
