# The Ultimate AI Platform & LLMOps Interview Cheatsheet

Este documento mapea la teoría de entrevistas técnicas de DevOps, SRE y Arquitectura de IA con las implementaciones reales de la **Biometric AI Platform**.

---

## 🏗️ 1. RAG & Data Architecture (Fierros y Datos)

### P1: ¿Cómo diseñás e implementás una arquitectura RAG para que sea escalable y eficiente en producción?
*   **La Teoría:** Un RAG (Retrieval-Augmented Generation) escalable desacopla la **Ingesta** (asincrónica, chunking, embeddings vectoriales) del **Runtime** (consulta rápida, búsqueda de similitud, inyección de contexto).
*   **En este proyecto HOY:** Utilizamos **BigQuery Vector Search**. El agente usa la herramienta `research_assistant.py` para consultar la tabla `knowledge_base`, utilizando `ML.DISTANCE` para encontrar vectores relevantes e inyectarlos dinámicamente en el prompt del LLM.
*   **Roadmap de Producción:** Mover la ingesta a un pipeline completamente *Event-Driven* usando Cloud Functions activadas por eventos de Storage (Ej: GCS triggers).

### P2: ¿Qué estrategia de chunking y overlap elegiste para los documentos y por qué?
*   **La Teoría:** El chunking rompe textos largos en piezas digeribles para no desbordar la ventana de contexto. El *overlap* (solapamiento) asegura que no se pierda la semántica (el hilo conductor) si una idea clave queda cortada entre dos chunks.
*   **En este proyecto HOY:** Implementado en `scripts/upload_knowledge.py`. Usamos `RecursiveCharacterTextSplitter` de LangChain con un `chunk_size` de 1000 caracteres y un `chunk_overlap` de 200, preservando la continuidad de conceptos fisiológicos complejos.
*   **Roadmap de Producción:** Implementar *Semantic Chunking*, donde los cortes se realizan basados en cambios de significado real (clustering) en lugar de una longitud fija de caracteres.

### P3: ¿Bases Vectoriales: Nativas (Pinecone/Qdrant) vs. Integradas (PostgreSQL+pgvector / BigQuery)?
*   **La Teoría:** Las bases nativas ofrecen menor latencia extrema y features avanzados. Las integradas (Postgres/BigQuery) reducen drásticamente la complejidad operativa (menos piezas móviles, misma seguridad, misma red, sin sincronización dual).
*   **En este proyecto HOY:** Apostamos por la simplicidad y acoplamiento de infraestructura: **BigQuery Vector Search**. Dado que nuestra telemetría (tablas estructuradas) ya vive en BigQuery, mantener los vectores en el mismo Data Lake simplifica el control de accesos e IAM.
*   **Roadmap de Producción:** Mantener soluciones integradas (migrando a `pgvector` en Cloud SQL si requerimos latencias sub-10 milisegundos en tiempo real), priorizando siempre reducir la complejidad de la arquitectura SRE.

### P4: ¿Cómo asegurás el aislamiento de datos (Multi-tenancy/Multi-usuario) en un entorno regulado?
*   **La Teoría:** El aislamiento a nivel de aplicación (filtrar por IDs) es vulnerable a errores humanos. A escala, se requieren Row-Level Security (RLS) en la base de datos o esquemas/namespaces separados por tenant.
*   **En este proyecto HOY:** Implementamos aislamiento estricto en la capa de aplicación. Cada endpoint en `main.py` y herramienta (ej. `etl_tool.py`, `retriever.py`) requiere obligatoriamente el `user_id`. Además, las consultas de exploración SQL validan mediante expresiones regulares que la cláusula `WHERE user_id =` esté presente antes de ejecutar (ver `data_scientist.py`).
*   **Roadmap de Producción:** Habilitar políticas de **Row-Level Security (RLS) nativas de PostgreSQL o BigQuery**, forzando el aislamiento en el propio motor de la base de datos, quitándole esa responsabilidad crítica al código Python.

### P5: ¿Cómo automatizás la ingesta asincrónica (event-driven) para evitar cuellos de botella?
*   **La Teoría:** Se utiliza una arquitectura de *Pub/Sub*. Un archivo llega al Storage, dispara un evento que despierta a un *worker* efímero, el cual calcula embeddings, actualiza la base vectorial y muere.
*   **En este proyecto HOY:** La sincronización de biometría está estructurada en trabajos ETL desacoplados (e.g., `etl_job.py`). Sin embargo, para documentos PDF/MD de conocimiento, usamos scripts manuales de carga masiva (`upload_knowledge.py`).
*   **Roadmap de Producción:** Convertir `upload_knowledge.py` en una Cloud Function (o un Job en Kubernetes vía Argo Events) que escuche eventos de un bucket de GCS (`storage.object.finalize`).

---

## 👁️ 2. Observabilidad, Tracing y Monitoreo (SRE de IA)

### P6: ¿Monitoring vs. Observability en LLMs?
*   **La Teoría:** *Monitoring* te dice si el servicio está caído (error 500, CPU al 90%). *Observability* te dice **por qué** el modelo dio una mala respuesta (analizando el input exacto, los chunks recuperados, el prompt ensamblado y la latencia de la llamada a OpenAI).
*   **En este proyecto HOY:** Tenemos monitoreo básico vía logging estructurado JSON (`api.json.log`). También logueamos métricas de FinOps.
*   **Roadmap de Producción:** Implementar OpenTelemetry puro, exportando no solo logs, sino trazas distribuidas completas.

### P7: ¿Por qué un APM tradicional queda corto y qué aporta Langfuse/LangSmith?
*   **La Teoría:** Datadog ve "una llamada POST lenta". Langfuse visualiza la "Cadena de Pensamiento": te muestra el prompt inyectado, qué herramienta falló, la evaluación del modelo intermedio y cuánto costó cada sub-paso de forma visual y jerárquica.
*   **En este proyecto HOY:** Dependemos de nuestra estructura de logs unificada, registrando invocaciones de herramientas y llamadas al LLM secuencialmente. Es funcional, pero difícil de depurar visualmente.
*   **Roadmap de Producción:** **Integrar Langfuse** (u otro framework de tracing de LLMs) envolviendo el `graph.py` (LangGraph) para ganar observabilidad visual del árbol de ejecución agéntica en tiempo real.

### P8: ¿Estructuración de Logs de IA a gran escala?
*   **La Teoría:** Logs legibles por máquina (JSON) centralizados con `trace_id` y `span_id` para correlacionar eventos a través de microservicios, sin perder legibilidad para desarrollo local.
*   **En este proyecto HOY:** (Skill activada: `unified-logging`). Usamos un manejador dual en `main.py`: `StreamHandler` con texto limpio para consola humana (con emojis y colores) y un `FileHandler` escribiendo en `api.json.log` para ingestión de máquinas (Fluentbit/Logstash).
*   **Roadmap de Producción:** Centralizar `api.json.log` en Google Cloud Logging / Datadog asegurando la propagación estricta de un `Correlation-ID` (header HTTP) desde el gateway web hasta el modelo subyacente.

### P9: ¿Implementación de OpenTelemetry nativo?
*   **La Teoría:** Instrumentar el código con OTel SDKs para generar Traces, Metrics y Logs estandarizados e inyectar el contexto de la traza (W3C Trace Context) en los headers de las peticiones HTTP/gRPC.
*   **Roadmap de Producción:** Añadir los wrappers de `opentelemetry-instrumentation-fastapi` y `opentelemetry-instrumentation-httpx` (para llamadas externas a APIs de LLMs). Enviar la telemetría a un colector central (OTel Collector) que distribuya hacia el backend de SRE elegido.

---

## 📊 3. FinOps & Cost Management

### P10: ¿Estrategias de mitigación de costos de APIs LLMs?
*   **La Teoría:** Usar modelos más baratos/rápidos (Small Language Models) para tareas de enrutamiento o extracción, y reservar los modelos pesados (GPT-4 / Claude 3.5 Sonnet) solo para síntesis compleja o razonamiento profundo. Implementar Caching Semántico.
*   **En este proyecto HOY:** (Arquitectura Híbrida). Usamos LLMs rápidos como evaluadores o extractores de memoria, reservando los motores densos para la síntesis de reportes biológicos. Hemos implementado un tracker FinOps rígido.
*   **Roadmap de Producción:** Migrar la inferencia básica a LLMs locales (como Llama 3 o Gemma 2b hospedados en nuestros propios clústeres) donde el costo marginal por token es cero.

### P11: ¿Auditoría y trackeo de consumo de tokens (FinOps) en tiempo real?
*   **La Teoría:** Interceptar las respuestas del LLM, parsear la metadata `usage` y almacenarla en una base analítica asociada a un Request ID, User ID y Feature.
*   **En este proyecto HOY:** **Completamente implementado.** `utils/finops.py` envuelve llamadas, extrae `input_tokens` y `output_tokens`, calcula el coste en USD basándose en una matriz de tarifas del modelo y lo persiste asincrónicamente en la tabla de BigQuery `finops_logs`.

### P12: ¿Semantic Caching (Caché Semántico) y su impacto?
*   **La Teoría:** Almacenar pares de "vector de pregunta" -> "respuesta". Si una nueva pregunta tiene un *Cosine Similarity* del 95% con una anterior, devolvemos el valor del caché. Impacto: 100% de ahorro en tokens para esa query y reducción de latencia de 3-5 segundos a <50ms.
*   **En este proyecto HOY:** Ausente. Cada petición se computa desde cero.
*   **Roadmap de Producción:** Integrar **RedisV** (Redis Vector Search) antes de golpear al router de LangGraph. Será el Quick Win #1 para mejorar métricas económicas.

---

## 🛡️ 4. Guardrails & Seguridad

### P13: ¿Guardrail vs. If/Else simple?
*   **La Teoría:** Un `if/else` evalúa condiciones lógicas exactas (ej. regex, listas negras). Un *Guardrail* utiliza modelos de NLP rápidos o reglas probabilísticas para evaluar semántica compleja (toxicidad, desviación del rol, riesgo clínico) que una regex no puede atrapar.
*   **En este proyecto HOY:** Dependemos de "Prompt Engineering" (instrucciones estrictas en los prompts del sistema, como "NUNCA des consejos médicos") y validación básica en código.
*   **Roadmap de Producción:** Implementar frameworks formales como **NVIDIA NeMo Guardrails** o Guardrails AI para validar estructuralmente los flujos antes de que el usuario vea la respuesta.

### P14: ¿Protección contra Prompt Injection y PII?
*   **La Teoría:** Sanitizar el input del usuario eliminando datos sensibles (tarjetas, DNI) antes de enviarlos a la nube pública del LLM. Validar la "intención" del prompt para detectar manipulaciones maliciosas.
*   **Roadmap de Producción:** Añadir analizadores de presidio (Microsoft Presidio) en la capa del gateway de FastAPI para enmascarar automáticamente PII (ej. nombres propios) antes de invocar cadenas de LLMs.

### P15: ¿Arquitectura de Seguridad: Acoplada vs. Proxy?
*   **La Teoría:** Si la seguridad está acoplada al agente, cada nuevo agente debe reimplementar la seguridad (riesgo de SRE). Debe estar en un **LLM Gateway / Proxy de infraestructura** (como LiteLLM proxy o Cloudflare API Gateway) que intercepte y valide todo tráfico saliente a OpenAI/Anthropic de manera centralizada.
*   **Roadmap de Producción:** Desacoplar la conexión LLM. Nuestro código Python apuntará a un Gateway LLM interno; este Gateway aplicará el guardrail y luego enrutará la petición al proveedor de la nube.

---

## 🧠 5. Evaluación de Modelos y Agentes (CI/CD)

### P16: ¿Calidad de software sin determinismo (Reemplazo de Unit Tests)?
*   **La Teoría:** Como el texto cambia en cada ejecución, validamos métricas como *Relevancia Contextual*, *Fidelidad a los Hechos* (Faithfulness) y *Precisión* evaluando el output contra matrices semánticas en vez de aserciones `==`.
*   **En este proyecto HOY:** Implementado parcialmente en `scripts/evaluate_agent.py`. Evaluamos la cadena RAG completa usando un dataset JSON para comprobar si responde correctamente sin alucinar.
*   **Roadmap de Producción:** Pasar de scripts manuales a integración nativa en los PRs de GitHub.

### P17: ¿Qué es un Golden Dataset?
*   **La Teoría:** Es una colección curada a mano de (Pregunta, Contexto Requerido, Respuesta Ideal). Sirve como ancla de calidad (baseline). Si modificás un prompt en el código, corrés todo el dataset para ver si rompiste casos de uso anteriores (Regression Testing).
*   **En este proyecto HOY:** Contamos con `tests/eval_dataset.json` que actúa como nuestra primera semilla de Golden Dataset.

### P18: ¿Estrategia LLM-as-a-Judge automatizada en CI/CD?
*   **La Teoría:** Usar un modelo potente (GPT-4) como juez para calificar de 1 a 5 la respuesta que generó nuestro agente más rápido/barato (Gemma/Llama).
*   **En este proyecto HOY:** El script `evaluate_agent.py` utiliza justamente un modelo evaluador dedicado (Configurado mediante la clase `Evaluator`) que puntúa la exactitud y fidelidad de los tests.
*   **Roadmap de Producción:** Configurar un pipeline de GitHub Actions (`.github/workflows/ci.yml`) que ejecute las evaluaciones. Si el *passing rate* cae por debajo del 90%, el merge del Pull Request se bloquea automáticamente.

---

## 🤖 6. Agentic AI & Orchestration

### P19: ¿Desafíos de SRE al correr modelos locales en Kubernetes?
*   **La Teoría:** Los contenedores que corren modelos necesitan planificadores (schedulers) conscientes de GPUs (Nvidia Device Plugin). Los modelos (pesos) son gigantes (10GB+), lo que hace que los arranques en frío (cold starts) destrocen los tiempos de escalado (HPA).
*   **Roadmap de Producción:** Usar estrategias de "Persistent Volumes" para cachear los pesos en el clúster o servir los modelos vía frameworks optimizados (vLLM / Ollama) desacoplados de los pods de la aplicación Python.

### P20: ¿Memoria Corto vs. Largo Plazo en LangGraph?
*   **La Teoría:** *Short-term memory* es el historial de la sesión actual, necesario para el contexto de la charla (manejado por el *Checkpointer* del grafo en memoria RAM). *Long-term memory* son hechos persistentes sobre el usuario, almacenados externamente (base de datos vectorial/OLTP).
*   **En este proyecto HOY:** Altamente maduro. LangGraph maneja el estado de la sesión, y tenemos un Agente `memory_manager` que extrae asincrónicamente "Nuggets Semánticos" (preferencias del usuario, molestias físicas) y los persiste a largo plazo en Firestore (`src/utils/firestore.py`).

### P21: ¿Qué es el Model Context Protocol (MCP) de Anthropic?
*   **La Teoría:** En lugar de que el modelo reciba datos o código, el modelo puede hablar un estándar unificado (MCP) para listar y consumir herramientas corporativas (bases de datos, repositorios, Slacks) directamente desde la infraestructura del cliente, sin mover datos masivos al modelo. Es SRE para interfaces de agentes.
*   **Roadmap de Producción:** Considerar adaptar nuestras herramientas y Data Lake para exponer una interfaz compatible con MCP, permitiendo que cualquier plataforma compatible con la IA interactúe con el backend del Coach Biométrico de manera plug-and-play.
