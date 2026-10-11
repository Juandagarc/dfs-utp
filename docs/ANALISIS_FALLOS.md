# Análisis de fallos

Este documento cubre las secciones **13**, **14**, **17** y **18** de la guía.

## 1. Caída de un nodo de almacenamiento (prueba obligatoria, sección 13)

### Procedimiento

1. Subir un archivo y averiguar dónde quedó:
   ```bash
   python client/dfs.py upload informe.pdf      # ej. stored on: node1, node3
   python client/dfs.py locate informe.pdf
   ```
2. Mostrar el archivo **físicamente** en ambos hosts:
   - Host B: `ls storage/node1/` (Windows: `dir storage\node1`), o abrir `http://<IP-B>:8001/files`.
   - Host D: `ls storage/node3/`.

   Los SHA-256 coinciden con el que reporta el coordinador.
3. **Detener node1** con `Ctrl+C` en el Host B, o desconectando su red. En unos 5 s (hasta ~20 s si se desconecta la red) el dashboard muestra node1 **DOWN** y el archivo **DEGRADED**.
4. Descargar de nuevo:
   ```bash
   python client/dfs.py download informe.pdf -o recuperado.pdf
   ```
   Salida esperada:
   ```
   served by : node3 (http://100.x.x.D:8001)
   failover  : skipped node1:DOWN(heartbeat)
   integrity : OK (sha256)
   ```
   La terminal de node3 registra `SERVED informe.pdf to <IP-A>`. Eso prueba que respondió la réplica y no node1.
5. *(Opcional)* Restaurar el factor de replicación mientras node1 sigue caído:
   ```bash
   python client/dfs.py repair          # copied informe.pdf: node3 -> node2
   ```
6. Reiniciar node1; el siguiente heartbeat lo marca **UP** otra vez.

### Resultado

El servicio sigue disponible después de la caída de un nodo porque cada archivo tiene una segunda copia en otro host. El coordinador detecta el fallo (por heartbeat o por error de conexión) y dirige la lectura hacia la réplica que sobrevive. Con 3 nodos y factor de replicación 2, **cualquier nodo puede caerse sin que ningún archivo quede inaccesible**. Si caen los dos nodos que tienen un mismo archivo, ese archivo responde HTTP 503, pero todos los demás siguen funcionando.

## 2. Caída del coordinador (análisis, sección 14)

### Procedimiento

Detener el coordinador (`Ctrl+C` en el Host A) mientras los 3 nodos siguen activos.

### Qué deja de funcionar

| Operación | ¿Funciona? | Por qué |
|---|---|---|
| Subir un archivo nuevo | ❌ | Solo el coordinador decide la ubicación y registra los metadatos |
| Listar o localizar archivos | ❌ | El índice archivo → nodos vive únicamente en el coordinador |
| Descarga normal (`dfs.py download`) | ❌ | El cliente solo conoce la dirección del coordinador |
| Dashboard | ❌ | Lo sirve el coordinador |
| Detección de fallos y reparación | ❌ | Los heartbeats y la reparación corren en el coordinador |

### Qué sigue funcionando

| Operación | ¿Funciona? | Por qué |
|---|---|---|
| Los nodos siguen activos y conservan sus datos | ✅ | Son procesos independientes en hosts independientes |
| Leer un archivo directamente de un nodo | ✅ | `GET http://<nodo>:8001/files/<nombre>` o `python client/dfs.py direct <nombre>`. Solo funciona si ya se conoce la ubicación (guardada en caché por un `ls` o `locate` anterior) |
| Endpoint de salud de los nodos | ✅ | `GET /health` en cada nodo |

Demostración:

```bash
python client/dfs.py ls                      # con el coordinador activo (guarda las ubicaciones)
# se detiene el coordinador
python client/dfs.py ls                      # ERROR: Cannot reach coordinator
python client/dfs.py direct informe.pdf      # Downloaded ... DIRECTLY from node3 (coordinator bypassed)
```

### Conclusión: ¿el coordinador es un SPOF?

**Sí.** El coordinador es un **punto único de fallo (SPOF) para el servicio**, aunque **no para los datos**. No se pierde ningún archivo, porque los bytes están en los nodos y los metadatos quedan guardados en `metadata.json`. Pero sin el coordinador los usuarios no pueden subir, buscar ni descargar por el punto de entrada normal, porque solo él sabe dónde está cada archivo.

### Alternativas propuestas

1. **Coordinador de respaldo con metadatos replicados** (el siguiente paso más simple). Un segundo coordinador en otro host recibe cada actualización de metadatos, o copia `metadata.json` periódicamente. Los clientes conocen ambas direcciones y cambian cuando el principal no responde. La elección de líder puede hacerse con un *lease* o un heartbeat entre ambos. Es el enfoque del NameNode de HDFS con Alta Disponibilidad.
2. **Reconstruir los metadatos desde los nodos.** Cada nodo ya expone `GET /files` con nombres y hashes. Un coordinador nuevo puede reconstruir el índice completo consultando a todos los nodos, así que su estado deja de ser único y pasa a ser recuperable.
3. **Metadatos replicados por consenso.** Tres coordinadores con Raft (por ejemplo, usando etcd) mantienen el índice consistente y eligen un nuevo líder automáticamente. Más robusto, pero más complejo.
4. **Eliminar el coordinador (descentralizado).** Los clientes calculan el anillo hash por sí mismos (*consistent hashing*) y hablan directamente con los nodos, como en Dynamo o Cassandra. Cualquier nodo puede servir de punto de entrada. Es lo más difícil de implementar, pero no deja ningún punto central.

## 3. Escalar de 3 a 100 nodos (sección 18)

| Aspecto | Con 3 nodos | Qué cambia con 100 nodos |
|---|---|---|
| Ubicación | `hash mod N` | `mod N` reubica casi todos los archivos cuando cambia N. Hay que pasar a **consistent hashing con nodos virtuales**, para que agregar o quitar un nodo mueva solo ~1/N de los archivos. |
| Factor de replicación | 2 | Con 100 máquinas los fallos son rutinarios. Conviene **R = 3**, con réplicas en racks o sedes diferentes. |
| Detección de fallos | El coordinador consulta cada nodo cada 3 s | 100 peticiones cada 3 s todavía es manejable, pero a mayor escala los nodos deben enviar su propio heartbeat, o usar un **protocolo gossip**. |
| Reparación | `/repair` manual | **Re-replicación automática en segundo plano**, con límite de velocidad para que un nodo caído no sature la red. |
| Metadatos | Un archivo JSON en memoria | Millones de archivos requieren una base de datos o un servicio de metadatos particionado y replicado. |
| Carga del coordinador | Todos los bytes pasan por él | Se vuelve un cuello de botella. El coordinador solo debería devolver ubicaciones, y los clientes transferir los datos **directamente con los nodos** (como en GFS y HDFS). |
| Archivos grandes | Archivo completo por nodo | Dividir los archivos en **bloques** (*chunks*) repartidos entre muchos nodos, para transferir en paralelo y balancear mejor. |
| Consistencia | Gana la última escritura | Versionado, o lecturas y escrituras por quórum (W + R > N), para manejar actualizaciones concurrentes. |
| Operación | Arranque manual | Contenedores o automatización, monitoreo y logs centralizados. |

## 4. Pregunta central (sección 17)

> *¿Por qué lo que construimos puede considerarse un Sistema Distribuido y no simplemente varios programas ejecutándose en computadores diferentes?*

1. **Un solo servicio, muchas máquinas.** El usuario interactúa con una sola dirección y un solo espacio de nombres de archivos. Dónde están los bytes queda oculto: eso es **transparencia de ubicación**. Los cuatro programas cooperan para una misma función; ninguno presta el servicio por sí solo.
2. **Comunicación real por red con un protocolo.** Componentes en 4 hosts con 4 IP distintas intercambian mensajes HTTP estructurados para escrituras, lecturas y heartbeats. Los logs muestran la IP remota de cada petición.
3. **El estado está distribuido.** El contenido de los archivos existe físicamente en discos diferentes. Los metadatos que los relacionan viven en otro host. Ninguna máquina contiene el sistema completo.
4. **Replicación con un propósito real.** Cada archivo existe en dos hosts, lo cual se verifica en disco y con SHA-256. El sistema usa esas copias: las lecturas pasan automáticamente a la réplica que sobrevive.
5. **Se manejan los fallos parciales.** La propiedad que define a un sistema distribuido es que una parte puede fallar mientras las demás continúan. Nuestro sistema detecta ese fallo (heartbeats) y sigue prestando el servicio (failover). Además, conoce su propio límite: el coordinador es un SPOF, y proponemos cómo eliminarlo.

Varios programas sin relación en computadores diferentes no tendrían ninguna de estas propiedades: ni servicio compartido, ni estado compartido, ni reacción cuando uno de ellos falla.
