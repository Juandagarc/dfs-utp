# Guion del video de sustentación

Duración objetivo: **10–12 minutos**. Cada integrante habla y ejecuta una parte de la demostración, como lo pide el docente.

**Antes de grabar**
- Los 4 hosts están en Tailscale, los nodos están corriendo y el coordinador también, con las IP reales.
- `storage/` está vacío en cada nodo y `coordinator/metadata.json` está borrado, para que la demo empiece desde cero.
- Tener listos 2 o 3 archivos de prueba (un PDF, una imagen, un texto).
- Forma de grabar: una videollamada (Meet, Zoom, Discord) donde cada integrante comparte la pantalla de su propia máquina. Eso demuestra que los hosts son máquinas diferentes.
- Cada uno mantiene visible la terminal de su nodo: los logs `STORED / SERVED` son la evidencia.

---

## Parte 1 — Jorge Pineda · Problema, arquitectura y red (≈ 3 min)

1. **Problema y servicio.** Guardar archivos en una sola máquina significa que un fallo lo pierde todo. Construimos un servicio distribuido de almacenamiento que se percibe como un solo sistema.
2. Mostrar el **diagrama de arquitectura** (README) y explicar los roles: coordinador, más 3 nodos de almacenamiento en hosts diferentes.
3. Mostrar la **tabla de infraestructura** con las IP reales ([DESPLIEGUE.md](DESPLIEGUE.md)).
4. Ejecutar `tailscale status`: 4 máquinas diferentes, 4 IP diferentes.
5. **Prueba de conectividad** desde el Host A:
   ```bash
   ping <IP-B>
   ping <IP-C>
   ping <IP-D>
   python scripts/check_connectivity.py
   ```
   Explicar: el ping demuestra la red, y `HTTP OK host=<nombre>` demuestra comunicación entre procesos con otra máquina.

## Parte 2 — Alan Giraldo · Coordinador y visión de un solo servicio (≈ 2.5 min)

1. Mostrar la terminal del coordinador. Al arrancar registra `HEARTBEAT nodeX is UP` para cada nodo.
2. Explicar sus responsabilidades: ubicación con el anillo hash, índice de metadatos, heartbeats cada 3 s y failover.
3. Abrir el **dashboard** en `http://<IP-A>:8000`: 3 nodos UP con sus hostnames reales.
4. **Subir** 2 o 3 archivos desde el dashboard. Resaltar que *el usuario nunca elige un nodo*: el coordinador decide e informa dónde guardó cada archivo.
5. Mostrar `coordinator/metadata.json`: el índice archivo → nodos, con su SHA-256.

## Parte 3 — Juan García · Nodos, distribución y replicación (≈ 2.5 min)

1. Explicar el rol del nodo: guarda réplicas en su propio disco, verifica el SHA-256 y entrega archivos.
2. Mostrar las terminales de los nodos: `STORED informe.pdf (...) from <IP-A>`. La petición llegó por red desde la IP del coordinador.
3. **Probar que los datos existen físicamente** en dos hosts diferentes:
   ```bash
   # en cada host que tiene el archivo
   ls -l storage/node1/          # Windows: dir storage\node1
   ```
   También abrir `http://<IP-nodo>:8001/files`: el SHA-256 es idéntico en ambas réplicas y coincide con el del coordinador.
4. Explicar la **distribución**: archivos diferentes quedan en pares de nodos diferentes, así que se usan los 3 nodos. Mostrarlo en la columna *Replicas* del dashboard.
5. Explicar la **replicación**: factor 2, escrituras en paralelo, escritura atómica `.part` → renombrar.

## Parte 4 — Juan Cano · Pruebas de fallo y análisis (≈ 3 min)

1. **Caída de un nodo (obligatoria).** Elegir un archivo guardado, por ejemplo, en node1 + node3. El dueño de node1 lo detiene con `Ctrl+C`.
   - Dashboard: node1 aparece **DOWN** en menos de 3 s y el archivo **DEGRADED**. Registro de eventos: `HEARTBEAT node1 is DOWN`.
   - Descargar el archivo otra vez (enlace del dashboard, o CLI):
     ```bash
     python client/dfs.py download informe.pdf -o recuperado.pdf
     ```
     → `served by: node3`, `failover: skipped node1:DOWN(heartbeat)`, `integrity: OK`.
   - La terminal de node3 muestra `SERVED informe.pdf`: respondió la réplica.
2. **Reparación:** clic en *Repair replicas* (o `dfs.py repair`) → el archivo se copia a node2 y vuelve a tener 2 réplicas vivas.
3. Reiniciar node1, que vuelve a aparecer **UP**.
4. **Caída del coordinador.** Detener el coordinador. Mostrar que `dfs.py ls` falla, pero `dfs.py direct informe.pdf` sigue descargando directamente desde un nodo. Conclusión: el coordinador es un **SPOF para el servicio, no para los datos**. Propuesta: coordinador de respaldo con metadatos replicados ([ANALISIS_FALLOS.md](ANALISIS_FALLOS.md)).
5. **Cierre (todos):** responder la pregunta central. ¿Por qué es un sistema distribuido? Un solo servicio, comunicación real por red, estado distribuido, replicación que realmente se usa y manejo de fallos parciales.

---

## Lista de verificación para la evaluación en vivo (sección 18)

| El docente va a… | Qué hacer | Respuesta corta |
|---|---|---|
| Pedir la IP de cada host y comprobar la conectividad | `tailscale ip -4` en cada host; `ping`; `check_connectivity.py` | "Cada host tiene su propia IP de Tailscale; el ping muestra la red y `/health` muestra el proceso respondiendo." |
| Pedir dónde está físicamente un archivo | `dfs.py locate <archivo>` → luego `ls storage/nodeX` en esos dos hosts | "El coordinador solo guarda el índice; los bytes están en estos dos discos, con el mismo SHA-256." |
| Detener un nodo al azar | Dejar que lo detenga | — |
| Pedir el recurso de nuevo | `dfs.py download <archivo>` y señalar `served by` y el log del nodo | "El coordinador saltó el nodo caído y respondió la réplica en nodeY." Si el nodo detenido no tenía réplica de ese archivo: "Ese nodo no tenía este archivo, así que no cambia nada." |
| Detener el coordinador | Mostrar que `ls` falla y que `direct` funciona | "Es SPOF del servicio, no de los datos. Solución: coordinador de respaldo, reconstruir metadatos desde los nodos, o Raft." |
| Preguntar qué cambia con 100 nodos | — | "Consistent hashing con nodos virtuales, R = 3, reparación automática, heartbeats por gossip, metadatos particionados, clientes transfiriendo directamente con los nodos, bloques." Ver [ANALISIS_FALLOS.md §3](ANALISIS_FALLOS.md#3-escalar-de-3-a-100-nodos-sección-18). |

**Consejo:** mientras un nodo está caído, suban un archivo nuevo. Irá solo a los 2 nodos vivos, lo que demuestra que la ubicación tiene en cuenta los fallos.
