Plan Maestro V2: PoC AI Infrastructure & Engineering (Garmin Toolkit)
Este documento actualiza la hoja de ruta para alinear el proyecto con roles de AI Software Engineer y AI Infrastructure Lead ($150K+ USD), integrando conceptos avanzados de agentes, evaluación de calidad y optimización operativa.
1. Visión de Sistema: De RAG Simple a Agentic RAG
El objetivo no es solo responder preguntas, sino crear un sistema que razone sobre los datos. El sistema utilizará herramientas específicas para resolver consultas complejas (ej. "Compara mi potencia de hoy con mi mejor marca de 2024").
[Image of Agentic RAG architecture with tool use]
Nuevos Componentes de Inteligencia:
Router Agent: Orquestador que decide si consultar la base vectorial (conceptos) o BigQuery (datos exactos).
Tool Set: Funciones de Python que ejecutan consultas SQL dinámicas o búsquedas semánticas.
Reasoning Loop: Ciclo de pensamiento para validar si la respuesta recuperada es útil antes de entregarla.
2. Roadmap Actualizado: Las 5 Capas del Éxito
Fase 1: Infraestructura Crítica (Terraform & GCP)
Mantenemos la base de SRE sólida pero orientada a IA.
Setup: GCS, BigQuery y Artifact Registry.
IAM & Security: Configuración de roles granulares para que la IA solo acceda a lo necesario (Principle of Least Privilege).
Networking: Private endpoints para asegurar que los datos biométricos no viajen por internet pública.
Fase 2: Data & Embedding Pipeline (Data Engineering)
Ingesta: Cloud Function que procesa archivos .FIT.
Vector Store: Implementación de LanceDB (o ChromaDB) para búsqueda semántica.
Metadata Enrichment: Añadir etiquetas de contexto (clima, tipo de equipo, hora del día) para mejorar la recuperación.
Fase 3: Agentic Backend (AI Engineering)
Aquí es donde demostramos los skills de las JDs de alto nivel.
Framework: Implementación con LangChain o LangGraph.
Memory: Gestión de historial de chat para que la IA recuerde conversaciones previas del usuario.
FastAPI Service: Exposición de una API asíncrona optimizada para baja latencia.
Fase 4: El Pipeline de Evaluación (AI Quality Assurance)
Diferenciador clave: demostrar que sabemos medir la "verdad" de la IA.
Framework: Implementación de Ragas (Retrieval Augmented Generation Assessment).
Métricas de Oro: Faithfulness (fidelidad a los datos), Answer Relevance (relevancia) y Context Precision.
Automated Testing: Pipeline que corre pruebas de evaluación ante cada cambio en el prompt.
[Image of LLM evaluation pipeline with Ragas framework]
Fase 5: Observabilidad & FinOps (Operational Excellence)
Token Tracking: Logging detallado del consumo de tokens por request y por usuario.
Cost Analysis: Dashboard que traduce tokens a dólares reales de costo operativo.
Performance Benchmarking: Medición de Time-to-First-Token (TTFT) y latencia total.
3. Tabla de Skills Demostrados vs. JD Requerido
Concepto del Proyecto
Skill en el JD
Impacto en el Sueldo
 
Agentic RAG / LangGraph
Multi-agent AI workflows
Alto (Demuestra Arquitectura)
Ragas / Eval Pipelines
LLM Evaluation Frameworks
Muy Alto (Confianza de Negocio)
Token & Cost Logging
Cost and Latency Optimization
Crítico (Mentalidad SRE/FinOps)
FastAPI / Async Python
High-performance Backend
Base (Senior Engineering)

Próxima Acción Inmediata
Comenzar con la estructura del repositorio en GitHub utilizando un enfoque de Monorepo para separar claramente la infraestructura de la lógica del Agente de IA.

