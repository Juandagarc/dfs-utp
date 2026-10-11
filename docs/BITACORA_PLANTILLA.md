# Bitácora del laboratorio — Plantilla

Esta es la estructura sugerida de la bitácora que se entrega en PDF. Sigue punto por punto lo que pidió el docente. Cada recuadro 📸 indica un pantallazo que se debe tomar **mientras se trabaja**: el docente pidió evidencia de todo el proceso, incluidos los errores, no solo del resultado final.

> Guarden los pantallazos en `docs/screenshots/` con el nombre sugerido (`01_tailscale_status.png`, …). Así es fácil armar el PDF al final.

---

## Portada

- Taller Parcial – Laboratorio de Sistemas Distribuidos
- Universidad Tecnológica de Pereira — Ingeniería de Sistemas y Computación
- Integrantes: Jorge Pineda · Alan Giraldo · Juan García · Juan Cano
- Docente: Alexander Bejarano
- Fecha de entrega
- Enlace al repositorio y al video

## 1. Descripción del problema y del servicio distribuido

Qué problema resuelve el sistema y qué servicio ofrece. Base: [ARQUITECTURA.md §1](ARQUITECTURA.md#1-propósito).

## 2. Diseño y arquitectura del sistema distribuido

- Diagrama de arquitectura con hosts, nodos, IP, puertos, protocolo y responsabilidades (del README, con las IP reales).
- Respuestas a las 7 preguntas de diseño: propósito, arquitectura, comunicación, datos, distribución, replicación y fallos. Base: [ARQUITECTURA.md](ARQUITECTURA.md).

## 3. Máquinas y nodos utilizados

| Host | Responsable | Rol | Equipo / SO | Hostname | IP | Puerto | Estado |
|---|---|---|---|---|---|---|---|
| A | | Coordinador | | | | 8000 | |
| B | | Nodo 1 | | | | 8001 | |
| C | | Nodo 2 | | | | 8001 | |
| D | | Nodo 3 | | | | 8001 | |

📸 `01_tailscale_status.png` — `tailscale status` con las 4 máquinas.
📸 `02_ip_hostA.png` … `05_ip_hostD.png` — `tailscale ip -4` (o `ipconfig`) en cada máquina, con el nombre del equipo visible.

## 4. Herramientas y tecnologías empleadas

Python, FastAPI, Uvicorn, httpx, Tailscale, Git/GitHub, sistemas operativos usados. Para cada una, una línea de justificación (ver [ARQUITECTURA.md §8](ARQUITECTURA.md#8-tecnologías-elegidas)).

## 5. Configuración realizada en cada máquina

Para **cada** host:
1. Instalación de Python y verificación de la versión. 📸 `06_python_version_X.png`
2. Instalación y conexión a Tailscale. 📸 `07_tailscale_login_X.png`
3. Clonación del repositorio y `pip install -r requirements.txt`. 📸 `08_pip_install_X.png`
4. Configuración del firewall (`open_firewall.ps1` o `ufw`). 📸 `09_firewall_X.png`
5. Solo en el Host A: edición de `config/nodes.json` con las IP reales. 📸 `10_nodes_json.png`

## 6. Desarrollo paso a paso

Contar el proceso en orden cronológico, con fecha:
1. Organización del grupo y reparto de roles.
2. Diseño de la arquitectura (antes de programar).
3. Implementación del nodo de almacenamiento.
4. Implementación del coordinador (ubicación, metadatos, heartbeats, failover).
5. Implementación del cliente CLI y del dashboard.
6. Pruebas locales de desarrollo (`tests/test_e2e.py`). 📸 `11_test_e2e.png`. Aclarar que solo fueron pruebas de código y que el despliegue evaluado usa 4 hosts.
7. Despliegue en los 4 hosts.

Incluir fragmentos de código clave con una explicación breve: elección de nodos con el anillo hash, bucle de heartbeat y failover en la descarga.

## 7. Pruebas de conectividad y comunicación entre nodos

📸 `12_ping_nodes.png` — `ping` desde el Host A hacia B, C y D.
📸 `13_check_connectivity.png` — `python scripts/check_connectivity.py` con `HTTP OK` y los hostnames.
📸 `14_node_started_X.png` — cada nodo arrancado escuchando en `0.0.0.0:8001`.
📸 `15_coordinator_heartbeats.png` — log del coordinador con `HEARTBEAT nodeX is UP` para los 3 nodos.
📸 `16_dashboard_all_up.png` — dashboard con los 3 nodos UP.

Explicar la diferencia entre conectividad (ping) y comunicación entre procesos (HTTP).

## 8. Distribución y replicación de la información

📸 `17_upload.png` — subida de varios archivos (dashboard o CLI) indicando en qué nodos quedó cada uno.
📸 `18_dashboard_files.png` — tabla de archivos con sus réplicas: se usan los 3 nodos.
📸 `19_metadata_json.png` — contenido de `coordinator/metadata.json`.
📸 `20_node_log_stored_X.png` — log del nodo con `STORED ... from <IP-A>`.
📸 `21_storage_dir_X.png` — `ls storage/nodeX` (o el explorador de archivos) en **cada** host que tiene la réplica.
📸 `22_node_files_endpoint.png` — `http://<IP-nodo>:8001/files` con el mismo SHA-256 en ambas réplicas.

## 9. Pruebas de funcionamiento

📸 `23_download_ok.png` — descarga normal con `served by` e `integrity: OK`.
📸 `24_api_docs.png` — `/docs` del coordinador (opcional).

## 10. Prueba de caída de uno de los nodos

📸 `25_before_failure.png` — dashboard: archivo con sus 2 réplicas OK.
📸 `26_node_stopped.png` — terminal del nodo detenido (`Ctrl+C`).
📸 `27_dashboard_node_down.png` — nodo DOWN, archivo DEGRADED, evento `HEARTBEAT nodeX is DOWN`.

## 11. Evidencia de que la información sigue disponible desde otro nodo

📸 `28_download_failover.png` — `dfs.py download` mostrando `served by: <réplica>` y `failover: skipped nodeX:DOWN(heartbeat)`.
📸 `29_replica_log_served.png` — log del nodo que respondió con `SERVED ...`.
📸 `30_repair.png` — `dfs.py repair` y el dashboard con 2 réplicas vivas otra vez (opcional).
📸 `31_node_back_up.png` — nodo reiniciado y marcado UP.

### Caída del coordinador

📸 `32_coordinator_stopped.png` — `dfs.py ls` falla.
📸 `33_direct_download.png` — `dfs.py direct` descarga desde un nodo sin el coordinador.

Análisis: qué sigue funcionando, qué no, por qué es un SPOF y la alternativa propuesta (ver [ANALISIS_FALLOS.md §2](ANALISIS_FALLOS.md#2-caída-del-coordinador-análisis-sección-14)).

## 12. Dificultades y errores encontrados

Registrar los errores **reales** que aparezcan, con pantallazo del error. Formato sugerido:

| # | Fecha | Error / dificultad | Causa | Solución aplicada | Pantallazo |
|---|---|---|---|---|---|
| 1 | | | | | `err_01_...png` |

Errores típicos que vale la pena capturar si les ocurren: timeout por el firewall de Windows, nodo arrancado en `127.0.0.1`, IP mal escrita en `nodes.json`, falta de `python-multipart`, máquinas en cuentas distintas de Tailscale, ping bloqueado en Windows, política de ejecución de PowerShell.

## 13. Soluciones aplicadas

Resumen de las correcciones y de los cambios de diseño que surgieron de esos errores.

## 14. Análisis técnico

- Ventajas del diseño.
- Limitaciones: coordinador SPOF, todos los bytes pasan por el coordinador, `hash mod N`, metadatos en un solo archivo.
- Qué cambiaría al pasar de 3 a 100 nodos ([ANALISIS_FALLOS.md §3](ANALISIS_FALLOS.md#3-escalar-de-3-a-100-nodos-sección-18)).
- Respuesta a la pregunta central ([ANALISIS_FALLOS.md §4](ANALISIS_FALLOS.md#4-pregunta-central-sección-17)).

## 15. Conclusiones del grupo

Entre 4 y 6 conclusiones **propias**, redactadas por el grupo, sobre lo aprendido: transparencia, replicación, fallos parciales, trabajo con máquinas reales en redes distintas.
