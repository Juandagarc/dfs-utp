# Guía de despliegue (4 hosts independientes)

> La guía **no** acepta ejecutar todo en un solo computador (sección 3). Cada componente de esta guía corre en una **máquina física diferente** con su **propia IP**.

## 1. Inventario de infraestructura

Se completa con los valores reales y se guarda un pantallazo de `tailscale status` como evidencia.

| Host | Responsable | Rol | Sistema operativo | IP Tailscale | Puerto | Estado |
|---|---|---|---|---|---|---|
| A | Jorge Pineda | Coordinador | _ej. Windows 11_ | `100.___.___.___` | 8000 | ☐ |
| B | Alan Giraldo | Nodo 1 | | `100.___.___.___` | 8001 | ☐ |
| C | Juan García | Nodo 2 | | `100.___.___.___` | 8001 | ☐ |
| D | Juan Cano | Nodo 3 | | `100.___.___.___` | 8001 | ☐ |

> La asignación de roles es una sugerencia; ajústenla según las máquinas que tengan.

## 2. Red: Tailscale (en todos los hosts)

1. Instalar Tailscale desde <https://tailscale.com/download>.
2. Iniciar sesión en **las cuatro** máquinas con la **misma cuenta**. Otra opción: una persona crea la red (*tailnet*) e invita a los demás desde *Admin console → Users → Invite*. Si cada uno usa su propia cuenta, hay que compartir cada máquina con los demás.
3. Obtener la IP de cada host:
   ```bash
   tailscale ip -4
   tailscale status       # lista las 4 máquinas → pantallazo para la bitácora
   ```
4. Anotar las IP en la tabla anterior.

**¿Están en la misma LAN del salón?** También funciona; usen las IP de la LAN (`ipconfig` / `ip a`). Se recomienda Tailscale porque funciona igual desde casas diferentes.

## 3. Software (en todos los hosts)

```bash
# Se requiere Python 3.10 o superior
python --version
git clone https://github.com/Juandagarc/dfs-utp.git
cd dfs-utp
pip install -r requirements.txt
```

> **Windows: ¿CMD o PowerShell?** Los comandos `.ps1`, `Set-ExecutionPolicy` y `$env:...` solo funcionan en **PowerShell**. Si abren **CMD** (Símbolo del sistema), usen las versiones `.bat`: `scripts\open_firewall.bat`, `scripts\start_node.bat node1` y `scripts\start_coordinator.bat`. No clonen el proyecto dentro de `C:\Windows\System32` (allí abre CMD como administrador): usen su carpeta de usuario, por ejemplo `cd %USERPROFILE%`.

### Firewall

- **Windows:** abrir PowerShell **como Administrador** en la carpeta del proyecto y ejecutar:
  ```powershell
  Set-ExecutionPolicy -Scope Process Bypass
  .\scripts\open_firewall.ps1
  ```
  Esto permite TCP 8000–8001 y el ping. Sin este paso, los otros hosts reciben timeouts. Es el error más común, así que conviene documentarlo en la bitácora.
  En **CMD como Administrador**: `scripts\open_firewall.bat`
- **Linux (ufw):** `sudo ufw allow 8000:8001/tcp`
- **macOS:** aceptar el aviso "permitir conexiones entrantes" para Python.

## 4. Arrancar los nodos de almacenamiento (Hosts B, C y D)

```bash
# Host B
./scripts/start_node.sh node1
# Host C
./scripts/start_node.sh node2
# Host D
./scripts/start_node.sh node3
```

En Windows:

```powershell
.\scripts\start_node.ps1 -NodeId node1
```

Cada uno se verifica localmente abriendo `http://127.0.0.1:8001/health`. El nodo **debe** escuchar en `0.0.0.0` (los scripts ya lo hacen). Si escucha en `127.0.0.1`, ningún otro host podrá conectarse.

## 5. Configurar y arrancar el coordinador (Host A)

Editar `config/nodes.json` con las **IP reales de Tailscale** de B, C y D:

```json
{
  "replication_factor": 2,
  "heartbeat_interval_s": 3,
  "heartbeat_timeout_s": 2,
  "nodes": [
    { "id": "node1", "url": "http://100.x.x.B:8001" },
    { "id": "node2", "url": "http://100.x.x.C:8001" },
    { "id": "node3", "url": "http://100.x.x.D:8001" }
  ]
}
```

Luego:

```bash
./scripts/start_coordinator.sh          # Windows: .\scripts\start_coordinator.ps1
```

El log debe mostrar `HEARTBEAT node1 is UP (...)` para los 3 nodos. El dashboard se abre en `http://<IP-A>:8000` desde **cualquiera** de los cuatro hosts.

## 6. Prueba de conectividad (sección 9 de la guía)

Desde el Host A:

```bash
ping 100.x.x.B
ping 100.x.x.C
ping 100.x.x.D
python scripts/check_connectivity.py
```

Salida esperada de `check_connectivity.py`:

```
node1  100.x.x.B  ping=OK   HTTP OK   host=ALAN-PC files=0
node2  100.x.x.C  ping=OK   HTTP OK   host=JUANG-LAPTOP files=0
node3  100.x.x.D  ping=OK   HTTP OK   host=juancano-mbp files=0
```

`ping` demuestra conectividad de red. `HTTP OK` demuestra **comunicación entre procesos**: la guía aclara que el ping por sí solo no basta. El campo `host` muestra que la respuesta viene de otra máquina.

Desde un nodo, se verifica que el coordinador responde con `curl http://<IP-A>:8000/nodes`.

## 7. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| El `ping` funciona pero HTTP da timeout | El firewall bloquea 8000/8001 | Paso de firewall de la sección 3 |
| El nodo funciona en su PC pero no desde otros | Se arrancó con `127.0.0.1` | Usar los scripts (`--host 0.0.0.0`) |
| El `ping` falla en Windows | ICMP bloqueado por defecto | `open_firewall.ps1` también habilita el ping |
| Un nodo aparece DOWN en el dashboard | IP o puerto incorrectos en `config/nodes.json` | Corregir la URL y reiniciar el coordinador |
| `ModuleNotFoundError: fastapi` | Faltan dependencias | `pip install -r requirements.txt` |
| La subida falla con un error de `python-multipart` | Falta el paquete | `pip install python-multipart` |
| No aparece la IP de Tailscale | La máquina no inició sesión | `tailscale up` y revisar la consola de administración |
| `127.0.0.1:8000` muestra una página "Service" de Windows Communication Foundation | Otro programa del PC ya usa el puerto 8000 | Arrancar el coordinador en otro puerto: `scripts\start_coordinator.bat 8080` y abrir `http://127.0.0.1:8080` |
| PowerShell no deja ejecutar el script | Política de ejecución | `Set-ExecutionPolicy -Scope Process Bypass` |
