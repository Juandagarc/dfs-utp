# Arquitectura y decisiones de diseño

Este documento responde las preguntas de diseño de la **sección 7** de la guía. Se escribió antes de implementar y se actualizó al final.

## 1. Propósito

**Problema.** Guardar archivos en una sola máquina es un punto único de pérdida: si su disco o su proceso falla, todos los archivos quedan inaccesibles.

**Servicio.** DFS-UTP ofrece almacenamiento de archivos. El usuario puede **subir**, **descargar**, **listar** y **borrar** archivos a través de una sola dirección. Internamente, los archivos se reparten y se replican en varios hosts independientes, así que sobreviven a la caída de cualquier nodo de almacenamiento.

## 2. Arquitectura: nodos y responsabilidades

| Nodo | Host | Responsabilidad |
|---|---|---|
| Coordinador | A | Punto de entrada. Decide la ubicación, mantiene el índice de metadatos, envía heartbeats, hace failover en las lecturas y repara réplicas. **No** guarda el contenido de los archivos de forma permanente (solo una copia temporal durante la subida). |
| Nodo 1 | B | Guarda réplicas en su disco, verifica la integridad, atiende lecturas y reporta su estado. |
| Nodo 2 | C | Igual que el Nodo 1. |
| Nodo 3 | D | Igual que el Nodo 1. |

Es una arquitectura de **metadatos centralizados y datos distribuidos**. Pertenece a la misma familia que GFS y HDFS: un maestro o NameNode guarda los metadatos, y los chunk servers o DataNodes guardan los datos.

```
            ┌────────────────────────────────┐
Usuario ──► │ COORDINADOR (Host A)           │
            │  metadata.json: archivo→nodos  │
            │  heartbeat (cada 3 s)          │
            └──────┬──────────┬─────────┬────┘
          HTTP     │          │         │
            ┌──────▼──┐ ┌─────▼───┐ ┌───▼─────┐
            │ NODO 1  │ │ NODO 2  │ │ NODO 3  │
            │ Host B  │ │ Host C  │ │ Host D  │
            │ storage/│ │ storage/│ │ storage/│
            └─────────┘ └─────────┘ └─────────┘
```

## 3. Comunicación

- **Protocolo:** HTTP/1.1 REST sobre TCP, implementado con **FastAPI** (servidor) y **httpx** (cliente asíncrono dentro del coordinador, síncrono en el CLI).
- **Red:** red privada **Tailscale** (WireGuard). Cada host recibe una IP estable `100.x.y.z`, alcanzable desde los demás sin importar la red física o el router de cada casa. Una LAN compartida también sirve.
- **Puertos:** coordinador `8000/tcp`, nodos `8001/tcp`.
- **Por qué HTTP/REST:**
  - Está permitido explícitamente en la guía.
  - Es fácil de inspeccionar con `curl` o el navegador durante la evaluación en vivo.
  - Permite *streaming* para archivos grandes.
  - Funciona igual en Windows, Linux y macOS.
  - FastAPI genera automáticamente una especificación interactiva (`/docs`).
- **Desventaja:** HTTP oculta los detalles de bajo nivel de los sockets. Para que la comunicación por red se vea, cada petición entre hosts queda registrada con la IP remota.

### Flujos de mensajes

**Subida**
```
Cliente ──POST /upload (multipart)──► Coordinador
Coordinador: calcula SHA-256, elige 2 nodos en el anillo hash
Coordinador ──PUT /files/x (X-SHA256)──► Nodo i   ┐ en paralelo
Coordinador ──PUT /files/x (X-SHA256)──► Nodo j   ┘
Nodo: escribe en x.part, verifica el hash, renombra atómicamente a x
Coordinador: registra {x: [i, j]} en metadata.json → responde 200
```

**Descarga**
```
Cliente ──GET /download/x──► Coordinador
Coordinador: busca [i, j]; intenta primero las réplicas vivas
Coordinador ──GET /files/x──► Nodo i   (¿falla?) ──► Nodo j
Coordinador ══stream══► Cliente   (encabezados: X-Served-By, X-Failed-Replicas)
```

**Heartbeat**
```
cada 3 s:  Coordinador ──GET /health──► cada nodo (ciclo independiente por nodo,
           timeout de 3 s y un reintento inmediato)
           2 heartbeats fallidos seguidos → el nodo se marca DOWN y se registra el evento
```

### Por qué 2 fallos seguidos y no 1

En las primeras pruebas con 3 PCs en casas diferentes, un nodo alternaba UP/DOWN cada 10–15 s aunque seguía funcionando: por la VPN, alguna respuesta tardaba más que el timeout. Se cambió a un timeout de 3 s, un reintento inmediato y DOWN solo tras 2 heartbeats fallidos seguidos. Es el compromiso clásico de un detector de fallos: más tolerancia evita **falsos positivos** (marcar caído un nodo lento), a cambio de tardar un poco más en detectar una caída real. Las descargas no esperan al heartbeat: si un nodo no responde durante una petición, se pasa a la réplica al instante.

## 4. Datos

| Qué | Dónde | Formato |
|---|---|---|
| Contenido de los archivos (réplicas) | Cada nodo: `./storage/<node_id>/<archivo>` | Bytes idénticos al original |
| Índice de metadatos | Coordinador: `coordinator/metadata.json` | `{nombre: {size, sha256, replicas[], uploaded_at}}` |
| Configuración de nodos | Coordinador: `config/nodes.json` | Ids de nodo, URL, factor de replicación, tiempos del heartbeat |
| Caché de ubicaciones (opcional) | Cliente: `~/.dfs_cache.json` | Últimas URL conocidas de las réplicas; solo la usa `dfs.py direct` |

Qué viaja por la red: los bytes de los archivos (subida, descarga y replicación), el encabezado con el SHA-256 y las respuestas JSON de salud y metadatos.

## 5. Distribución: cómo se elige el nodo

1. Se ordenan los ids de los nodos configurados: `[node1, node2, node3]`.
2. Se calcula `inicio = SHA-256(nombre_archivo) mod N`.
3. Se recorre el anillo en sentido horario desde `inicio` y se toman los primeros **R** nodos que el heartbeat reporta **vivos** (R = factor de replicación = 2).

Propiedades:
- **Determinística:** el mismo nombre siempre va a los mismos nodos, lo que facilita razonar y depurar.
- **Balanceada:** el hash reparte nombres distintos de forma uniforme entre los nodos.
- **Consciente de fallos:** si un nodo está caído al momento de subir, el siguiente nodo vivo toma su lugar.

## 6. Replicación

- **Todos** los archivos se guardan en **R = 2 nodos distintos** (configurable en `config/nodes.json`).
- Las dos escrituras se hacen **en paralelo**. La subida tiene éxito si al menos una escritura funciona. Si funcionan menos de R, el archivo se marca `under_replicated` y el dashboard muestra **DEGRADED**.
- Cada réplica se verifica con SHA-256 y se escribe de forma atómica (`.part` y luego renombrar), así que nadie lee un archivo a medio escribir.
- `POST /repair` restaura R: para cada archivo con menos de R réplicas vivas, lo copia desde una réplica viva hacia otro nodo vivo y actualiza el índice.

Con 3 nodos y R = 2, el sistema tolera **la caída de 1 nodo sin perder la disponibilidad de ningún archivo**.

## 7. Fallos

| Fallo | Detección | Comportamiento |
|---|---|---|
| Se detiene un nodo de almacenamiento | 2 heartbeats fallidos seguidos (≈ 5 s si se detiene el proceso; hasta ~20 s si el host se cuelga o pierde la red) o error de conexión durante una petición | Se marca DOWN. Las descargas se entregan desde la otra réplica. Las subidas nuevas van solo a nodos vivos. `/repair` vuelve a crear las réplicas faltantes. |
| El nodo vuelve | El siguiente heartbeat responde | Se marca UP. Sus archivos siguen en disco y vuelven a estar disponibles. |
| Transferencia corrupta | El SHA-256 no coincide en el nodo | La escritura se rechaza (HTTP 422). El cliente también verifica el hash después de descargar. |
| Ambas réplicas de un archivo caídas | Fallan todos los intentos de lectura | HTTP 503 "No replica available". Los demás archivos siguen funcionando. |
| Se detiene el coordinador | Los clientes no pueden conectarse | Se detienen la subida, el listado y la descarga normal. Los nodos siguen funcionando y entregan archivos directamente. Ver [ANALISIS_FALLOS.md](ANALISIS_FALLOS.md). |

## 8. Tecnologías elegidas

| Elección | Razón |
|---|---|
| Python 3 | Todos los integrantes lo conocen y corre en cualquier sistema operativo. |
| FastAPI + Uvicorn | E/S asíncrona, así que los heartbeats y las transferencias corren al mismo tiempo. Poco código y `/docs` automático. |
| httpx | Cliente HTTP asíncrono con *streaming* y timeouts. |
| Tailscale | Conecta hosts ubicados en casas diferentes sin abrir puertos en el router. |
| Metadatos en un archivo JSON | Simple y legible, así que se puede revisar en vivo. Sobrevive a reinicios del coordinador. |
