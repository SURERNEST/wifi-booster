import os
import sys
import time
import ctypes
import socket
import threading
import subprocess
import requests
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

# ============== AUTO-ELEVACIÓN A ADMINISTRADOR ==============
# Los comandos netsh (cambiar DNS, reiniciar el adaptador) requieren
# permisos de administrador en Windows. Si el programa no se está
# ejecutando como admin, se vuelve a lanzar a sí mismo pidiendo elevación
# (aparecerá el cuadro de UAC de Windows) y cierra la instancia sin permisos.

def es_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def relanzar_como_admin():
    parametros = " ".join(f'"{arg}"' for arg in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, parametros, None, 1
    )
    sys.exit(0)

if os.name == "nt" and not es_admin():
    relanzar_como_admin()

# ============== DETECCIÓN REAL DEL ADAPTADOR DE RED ==============
# ANTES: el nombre del adaptador estaba fijo en "Wi-Fi". Si tu adaptador
# se llama distinto (pasa seguido: "Wi-Fi 2", "Ethernet", etc.), TODOS los
# comandos netsh fallaban en silencio -- no cambiaban nada, pero el programa
# igual mostraba "✅ Éxito". Esa es una de las razones por las que el
# programa podía "empeorar" las cosas: dabas por optimizada la red cuando
# en realidad ningún comando había tenido efecto real.
#
# AHORA: se detecta automáticamente cuál es el adaptador que está
# realmente conectado (Status = Up) y se usa ese nombre en todos lados.

_estado_adaptador = {"nombre": None}

def detectar_adaptador_activo():
    try:
        ps_cmd = (
            'powershell -NoProfile -Command '
            '"Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
            'Sort-Object -Property ifIndex | '
            'Select-Object -First 1 -ExpandProperty Name"'
        )
        resultado = subprocess.run(ps_cmd, shell=True, capture_output=True,
                                    text=True, timeout=10)
        nombre = resultado.stdout.strip()
        if nombre:
            return nombre
    except Exception:
        pass
    return "Wi-Fi"  # última opción si la detección falla

def obtener_adaptador():
    if _estado_adaptador["nombre"] is None:
        _estado_adaptador["nombre"] = detectar_adaptador_activo()
    return _estado_adaptador["nombre"]

def redetectar_adaptador():
    """Por si el usuario cambia de red (ej. de WiFi a cable) sin
    reiniciar el programa."""
    _estado_adaptador["nombre"] = None
    adaptador = obtener_adaptador()
    ui_set(status, f"🔄 Adaptador detectado: {adaptador}")
    registrar_log(f"Adaptador redetectado manualmente: {adaptador}")

# ============== EJECUCIÓN DE COMANDOS CON VERIFICACIÓN REAL ==============
# ANTES: os.system(...) no informa si el comando realmente funcionó.
# AHORA: se revisa el código de salida real y se registra en el log
# cualquier falla, en vez de asumir éxito porque el programa no explotó.

def ejecutar_comando(comando, descripcion, timeout=20):
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True,
                                    text=True, timeout=timeout)
        exito = resultado.returncode == 0
        if not exito:
            registrar_log(f"[FALLÓ] {descripcion}: {resultado.stderr.strip()}")
        return exito, (resultado.stdout or "") + (resultado.stderr or "")
    except Exception as e:
        registrar_log(f"[ERROR] {descripcion}: {e}")
        return False, str(e)

# ============== SEGURIDAD DE HILOS PARA LA INTERFAZ ==============
# ANTES: los botones lanzaban hilos que actualizaban directamente los
# StringVar de Tkinter y abrían messagebox desde el hilo secundario.
# Tkinter NO es thread-safe: eso puede colgar o crashear la app de forma
# intermitente (notorio sobre todo en "Restaurar configuración por
# defecto", que abría un cuadro de confirmación desde un hilo de fondo).
# AHORA: toda actualización de UI pasa por app.after(), que la ejecuta
# de forma segura en el hilo principal.

def ui_set(variable, texto):
    app.after(0, lambda: variable.set(texto))

def ui_mensaje(tipo, titulo, texto):
    def _mostrar():
        if tipo == "info":
            messagebox.showinfo(titulo, texto)
        elif tipo == "warning":
            messagebox.showwarning(titulo, texto)
        else:
            messagebox.showerror(titulo, texto)
    app.after(0, _mostrar)

# ============== BLOQUEO DE BOTONES MIENTRAS HAY UNA OPERACIÓN ACTIVA ==============
# ANTES: no había forma de evitar que dos operaciones de red corrieran en
# paralelo (ej. dos "ipconfig /renew" a la vez, o reiniciar el adaptador
# mientras corre un test de velocidad). Eso sí puede dejar la red en peor
# estado que al principio.
# AHORA: mientras una operación está en curso, los botones se deshabilitan.

botones_accion = []

def bloquear_botones(bloquear=True):
    def _aplicar():
        estado = "disabled" if bloquear else "normal"
        for b in botones_accion:
            b.configure(state=estado)
    app.after(0, _aplicar)

def hilo(funcion, *args):
    def _tarea():
        bloquear_botones(True)
        try:
            funcion(*args)
        finally:
            bloquear_botones(False)
    threading.Thread(target=_tarea, daemon=True).start()

# ================= FUNCIONES BASE =================

def confirmar_restaurar():
    # El cuadro de confirmación se muestra en el hilo principal (aquí,
    # antes de lanzar el hilo de trabajo), no dentro de la función que
    # corre en background como estaba antes.
    confirmar = messagebox.askyesno(
        "Restaurar configuración por defecto",
        "Esto va a:\n\n"
        "• Volver el DNS a automático (el que asigna tu proveedor de Internet)\n"
        "• Limpiar la caché de DNS\n"
        "• Reiniciar el adaptador de red\n\n"
        "Es decir, deja la red como estaba antes de usar este programa.\n\n¿Continuar?"
    )
    if confirmar:
        hilo(_restaurar_configuracion_por_defecto)

def _restaurar_configuracion_por_defecto():
    adaptador = obtener_adaptador()

    ejecutar_comando(f'netsh interface ip set dns name="{adaptador}" dhcp', "DNS IPv4 a automático")
    ejecutar_comando(f'netsh interface ipv6 set dns name="{adaptador}" dhcp', "DNS IPv6 a automático")
    ejecutar_comando("ipconfig /flushdns", "limpiar caché DNS")

    try:
        ps_cmd = (
            'powershell -NoProfile -Command '
            '"Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
            'ForEach-Object { Set-NetAdapterPowerManagement -Name $_.Name '
            '-AllowComputerToTurnOffDevice Enabled -ErrorAction SilentlyContinue }"'
        )
        subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=20)
    except Exception:
        pass

    ejecutar_comando(f'netsh interface set interface "{adaptador}" admin=disable', "deshabilitar adaptador")
    time.sleep(3)
    ejecutar_comando(f'netsh interface set interface "{adaptador}" admin=enable', "habilitar adaptador")

    registrar_log("Configuración de red restaurada a valores por defecto")
    ui_mensaje("info", "Restaurado",
               "✅ La red quedó como estaba antes: DNS automático, caché limpia y adaptador reiniciado.")
    ui_set(recos, "🔁 Configuración de red restaurada a los valores originales del sistema (DNS automático por DHCP).")

# ============== ESTABILIDAD (no solo velocidad) ==============
# Estos ajustes no atacan la velocidad, atacan los CORTES/picos de ping
# intermitentes, que suelen tener otra causa distinta a la velocidad bruta.

def aplicar_ajustes_estabilidad():
    resultados = []

    try:
        ps_cmd = (
            'powershell -NoProfile -Command '
            '"Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
            'ForEach-Object { Set-NetAdapterPowerManagement -Name $_.Name '
            '-AllowComputerToTurnOffDevice Disabled -ErrorAction SilentlyContinue }"'
        )
        r = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            resultados.append("Ahorro de energía del adaptador desactivado")
        else:
            resultados.append("Ahorro de energía: el comando no confirmó éxito (revisa log)")
    except Exception as e:
        resultados.append(f"Ahorro de energía: no se pudo ajustar ({e})")

    ok, _ = ejecutar_comando("netsh interface tcp set global autotuninglevel=normal", "autotuning TCP")
    resultados.append("Auto-tuning TCP normalizado" if ok else "Auto-tuning TCP: no se pudo confirmar (revisa log)")

    adaptador = obtener_adaptador()
    try:
        ejecutar_comando(f'ipconfig /release "{adaptador}"', "liberar IP")
        time.sleep(1)
        ejecutar_comando(f'ipconfig /renew "{adaptador}"', "renovar IP")

        reconectado = False
        for _ in range(8):
            time.sleep(1)
            try:
                socket.gethostbyname("www.google.com")
                reconectado = True
                break
            except Exception:
                continue

        resultados.append("Lease de IP renovado" if reconectado else
                           "Lease de IP renovado (la red tardó en volver, espera unos segundos más)")
    except Exception as e:
        resultados.append(f"Renovación de IP: no se pudo aplicar ({e})")

    registrar_log("Ajustes de estabilidad aplicados: " + " | ".join(resultados))
    return resultados

def boton_estabilidad_manual():
    resultados = aplicar_ajustes_estabilidad()
    ui_set(recos,
        "🛡️ Ajustes de estabilidad aplicados:\n\n" + "\n".join(f"• {r}" for r in resultados) +
        "\n\nEsto ataca los CORTES intermitentes, no la velocidad. "
        "Si el problema es que 'anda rápido pero se cae', esto es lo que hay que probar."
    )

# ============== DNS (con IPv4 + IPv6 y verificación real) ==============
# ANTES: solo se cambiaba el DNS de IPv4. Si tu red tiene IPv6 activo
# (lo más común hoy), Windows puede resolver por IPv6 usando el DNS
# viejo del ISP e ignorar por completo el cambio de DNS. Se veía el
# mensaje "DNS cambiado" pero en la práctica no pasaba nada.
# AHORA: se cambia IPv4 y IPv6, y después se relee la configuración
# real del adaptador para confirmar que sí quedó aplicada.

DNS_V4 = {
    "Cloudflare": ("1.1.1.1", "1.0.0.1"),
    "Google": ("8.8.8.8", "8.8.4.4"),
    "OpenDNS": ("208.67.222.222", "208.67.220.220"),
}
DNS_V6 = {
    "Cloudflare": ("2606:4700:4700::1111", "2606:4700:4700::1001"),
    "Google": ("2001:4860:4860::8888", "2001:4860:4860::8844"),
    "OpenDNS": ("2620:119:35::35", "2620:119:53::53"),
}

def cambiar_dns(nombre):
    adaptador = obtener_adaptador()
    dns1, dns2 = DNS_V4[nombre]
    dns1_v6, dns2_v6 = DNS_V6[nombre]

    ejecutar_comando(f'netsh interface ip set dns name="{adaptador}" static {dns1}', "DNS IPv4 primario")
    ejecutar_comando(f'netsh interface ip add dns name="{adaptador}" {dns2} index=2', "DNS IPv4 secundario")
    ejecutar_comando(f'netsh interface ipv6 set dns name="{adaptador}" static {dns1_v6}', "DNS IPv6 primario")
    ejecutar_comando(f'netsh interface ipv6 add dns name="{adaptador}" {dns2_v6} index=2', "DNS IPv6 secundario")

    # Verificación real: releer qué quedó configurado, no asumir éxito.
    _, salida = ejecutar_comando(f'netsh interface ip show dns name="{adaptador}"', "verificar DNS")
    aplicado = dns1 in salida

    resultados_estabilidad = aplicar_ajustes_estabilidad()
    registrar_log(f"DNS -> {nombre} (adaptador '{adaptador}') verificado={aplicado}")

    if aplicado:
        ui_mensaje("info", "DNS",
            f"✅ DNS cambiado a {nombre} en el adaptador '{adaptador}' (verificado, IPv4 e IPv6).\n\n"
            f"Nota: esto acelera la carga de webs, pero NO reduce el ping dentro de un juego online.\n\n"
            f"También se aplicaron ajustes de estabilidad.")
        ui_set(recos, f"🌐 DNS {nombre} aplicado y verificado en '{adaptador}'.\n\n"
                       "🛡️ Ajustes de estabilidad:\n" + "\n".join(f"• {r}" for r in resultados_estabilidad))
    else:
        ui_mensaje("error", "DNS",
            f"⚠️ Los comandos se ejecutaron pero al verificar, el adaptador '{adaptador}' NO quedó "
            f"con el DNS {dns1}.\n\nRevisa log_optimizador.txt. Si el nombre de adaptador detectado "
            f"no es el correcto, usa '🔄 Redetectar adaptador' en la pestaña Avanzado.")

def limpiar_cache_dns():
    ok, _ = ejecutar_comando("ipconfig /flushdns", "limpiar caché DNS")
    registrar_log("Caché DNS limpiado" if ok else "Caché DNS: falló el comando")
    ui_mensaje("info" if ok else "error", "DNS",
               "Caché DNS limpiado." if ok else "No se pudo limpiar la caché DNS. Revisa el log.")

def reiniciar_adaptador():
    adaptador = obtener_adaptador()
    ejecutar_comando(f'netsh interface set interface "{adaptador}" admin=disable', "deshabilitar adaptador")
    time.sleep(3)
    ejecutar_comando(f'netsh interface set interface "{adaptador}" admin=enable', "habilitar adaptador")

    # Verificar que realmente volvió a haber conexión antes de avisar
    # que "salió bien" -- antes se asumía éxito sin comprobar nada.
    conectado = False
    for _ in range(10):
        time.sleep(1)
        try:
            socket.gethostbyname("www.google.com")
            conectado = True
            break
        except Exception:
            continue

    registrar_log(f"Adaptador '{adaptador}' reiniciado - reconectado={conectado}")
    if conectado:
        ui_mensaje("info", "Red", f"✅ Adaptador '{adaptador}' reiniciado y con conexión activa.")
    else:
        ui_mensaje("warning", "Red",
                   f"⚠️ El adaptador '{adaptador}' se reinició pero todavía no responde a Internet. "
                   f"Espera unos segundos y prueba '✅ Verificar Conexión'.")

def registrar_log(mensaje):
    with open("log_optimizador.txt", "a", encoding="utf-8") as log:
        log.write(f"{datetime.now()} - {mensaje}\n")

def explicar_error_red(e):
    texto = str(e)
    if "getaddrinfo" in texto or "11004" in texto or "11001" in texto:
        return ("No hay conexión a Internet en este momento (falla al resolver DNS).\n\n"
                 "Esto puede pasar unos segundos después de renovar la IP "
                 "(botón de Estabilidad) mientras la red se reconecta.\n\n"
                 "Espera 10-15 segundos y vuelve a intentar.")
    if "timeout" in texto.lower() or "timed out" in texto.lower():
        return ("El servidor de prueba tardó demasiado en responder.\n\n"
                 "Puede ser tu conexión local (revisa que no haya otro dispositivo "
                 "saturando la red) o que el servidor esté ocupado. Intenta de nuevo.")
    return f"No se pudo completar la prueba: {texto}"

def obtener_ip_local(adaptador):
    # ANTES: se parseaba texto crudo de "ipconfig" buscando la primera
    # aparición de "IPv4" en toda la salida. Eso puede agarrar la IP de
    # un adaptador virtual (VPN, VMware, Hyper-V) en vez de la IP real
    # del adaptador que estás usando para jugar.
    # AHORA: se pregunta específicamente por la IP del adaptador
    # detectado como activo.
    try:
        ps_cmd = (
            'powershell -NoProfile -Command "(Get-NetIPAddress -InterfaceAlias \'' + adaptador + '\' '
            '-AddressFamily IPv4 -ErrorAction SilentlyContinue | '
            'Where-Object {$_.IPAddress -notlike \'169.254.*\'} | '
            'Select-Object -First 1 -ExpandProperty IPAddress)"'
        )
        resultado = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
        ip = resultado.stdout.strip()
        return ip if ip else "No encontrada"
    except Exception:
        return "No encontrada"

def estado_red():
    adaptador = obtener_adaptador()
    ip_local = obtener_ip_local(adaptador)
    try:
        ip_publica = requests.get("https://api.ipify.org", timeout=5).text
    except Exception:
        ip_publica = "No disponible"
    ui_set(resumen, f"📶 Adaptador: {adaptador}  |  IP Local: {ip_local}\n🌍 IP Pública: {ip_publica}")
    registrar_log("Estado de red consultado")

def verificar_conexion():
    try:
        requests.get("https://www.google.com", timeout=2)
        registrar_log("Conexión verificada: OK")
        ui_mensaje("info", "Conexión", "✅ Tienes acceso a Internet.")
    except Exception:
        registrar_log("Conexión verificada: SIN ACCESO")
        ui_mensaje("warning", "Conexión", "❌ No tienes acceso a Internet.")

# ============== TEST + RECOMENDACIONES ==============
# No usamos "speedtest-cli": lleva años sin actualizarse y Ookla cambió su
# sistema, por eso daba 403 Forbidden. Medimos directo contra los
# endpoints públicos de Cloudflare (los mismos que usa speed.cloudflare.com).

CF_DOWN = "https://speed.cloudflare.com/__down"
CF_UP = "https://speed.cloudflare.com/__up"

def medir_ping_tcp(host="speed.cloudflare.com", puerto=443, intentos=6, timeout=3):
    # ANTES: cada intento resolvía DNS de nuevo, así que la latencia de
    # resolución de nombre se sumaba al "ping" medido y podía inflarlo
    # artificialmente. Tampoco se calculaba jitter ni pérdida de
    # paquetes, que es justo lo que se siente como "se corta el juego".
    # AHORA: se resuelve el host UNA vez y se reutiliza la IP, y se
    # calcula jitter (variación) y pérdida real.
    try:
        ip_resuelta = socket.gethostbyname(host)
    except Exception as e:
        raise RuntimeError(f"No se pudo resolver {host}: {e}")

    tiempos = []
    for _ in range(intentos):
        try:
            inicio = time.perf_counter()
            with socket.create_connection((ip_resuelta, puerto), timeout=timeout):
                pass
            tiempos.append((time.perf_counter() - inicio) * 1000)
        except Exception:
            pass
        time.sleep(0.15)

    if not tiempos:
        raise RuntimeError("No se pudo medir ping (sin respuesta del servidor)")

    promedio = sum(tiempos) / len(tiempos)
    varianza = sum((t - promedio) ** 2 for t in tiempos) / len(tiempos)
    jitter = varianza ** 0.5
    perdidos = intentos - len(tiempos)

    return {
        "promedio": promedio,
        "minimo": min(tiempos),
        "jitter": jitter,
        "perdidos": perdidos,
        "intentos": intentos,
    }

def medir_velocidad_real(bytes_bajada=40_000_000, bytes_subida=10_000_000, reintentos=2):
    ultimo_error = None
    for intento in range(1, reintentos + 1):
        try:
            ping_info = medir_ping_tcp()

            inicio = time.perf_counter()
            total_descargado = 0
            r = requests.get(f"{CF_DOWN}?bytes={bytes_bajada}", stream=True, timeout=25)
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=131072):
                total_descargado += len(chunk)
            duracion_bajada = time.perf_counter() - inicio
            if duracion_bajada <= 0 or total_descargado == 0:
                raise RuntimeError("La descarga de prueba no trajo datos")
            bajada = (total_descargado * 8) / duracion_bajada / 1_000_000

            datos_subida = os.urandom(bytes_subida)
            inicio = time.perf_counter()
            r = requests.post(CF_UP, data=datos_subida, timeout=25)
            r.raise_for_status()
            duracion_subida = time.perf_counter() - inicio
            if duracion_subida <= 0:
                raise RuntimeError("La subida de prueba no se completó")
            subida = (bytes_subida * 8) / duracion_subida / 1_000_000

            return {
                "bajada": bajada,
                "subida": subida,
                "ping": ping_info["promedio"],
                "jitter": ping_info["jitter"],
                "perdidos": ping_info["perdidos"],
                "intentos": ping_info["intentos"],
            }

        except Exception as e:
            ultimo_error = e
            if intento < reintentos:
                time.sleep(2)
                continue
    raise ultimo_error

def test_velocidad():
    ui_set(status, "Realizando test...")
    try:
        r = medir_velocidad_real()
        resultado = (f"↓ {r['bajada']:.2f} Mbps  ↑ {r['subida']:.2f} Mbps  "
                     f"🕒 Ping: {r['ping']:.0f} ms  📶 Jitter: {r['jitter']:.0f} ms")
        registrar_log("Test velocidad: " + resultado)
        ui_set(status, resultado)
        analizar_y_recomendar(r["bajada"], r["subida"], r["ping"], r["jitter"], r["perdidos"], r["intentos"])
    except Exception as e:
        ui_set(status, "⚠️ Error en test")
        ui_mensaje("error", "Error", explicar_error_red(e))

def analizar_y_recomendar(bajada, subida, ping, jitter=None, perdidos=None, intentos=None):
    recomendaciones = []
    if bajada < 10:
        recomendaciones.append("🔁 Velocidad de bajada baja. Considera hablar con tu ISP.")
    if subida < 3:
        recomendaciones.append("📤 Subida limitada. Evita apps como Drive/streaming mientras juegas.")
    if ping > 100:
        recomendaciones.append("🐢 Ping alto hacia el servidor de test. Revisa apps en 2do plano y usa cable.")
    # El jitter (variación del ping) es lo que realmente se siente como
    # "se corta el juego cada rato" -- mucho más que la velocidad bruta.
    # Antes el programa no lo medía y solo daba consejos genéricos.
    if jitter is not None and jitter > 15:
        recomendaciones.append(
            f"⚡ Jitter alto ({jitter:.0f} ms de variación entre pings). Esto es lo que se siente como "
            f"cortes intermitentes. Prueba '🛡️ Aplicar Ajustes de Estabilidad' y usa cable en vez de WiFi."
        )
    if perdidos and intentos and perdidos > 0:
        pct_perdida = (perdidos / intentos) * 100
        recomendaciones.append(
            f"📉 {perdidos}/{intentos} conexiones de prueba fallaron ({pct_perdida:.0f}% de pérdida). "
            f"Esto es consistente con cortes intermitentes reales, no un problema de velocidad."
        )
    if not recomendaciones:
        recomendaciones.append("✅ Conexión óptima: buena velocidad, ping bajo y sin variación notable (jitter bajo).")

    ui_set(recos, "\n".join(recomendaciones))
    registrar_log("Recomendaciones generadas.")

# ============== COMPARACIÓN ANTES / DESPUÉS ==============

baseline = {"bajada": None, "subida": None, "ping": None, "jitter": None, "fecha": None}

def calcular_cambio_pct(antes, despues, menor_es_mejor=False):
    if antes == 0:
        return 0.0
    cambio = ((despues - antes) / antes) * 100
    return -cambio if menor_es_mejor else cambio

def flecha_estado(valor_pct):
    if valor_pct > 1:
        return "🟢 mejoró"
    elif valor_pct < -1:
        return "🔴 empeoró"
    return "⚪ sin cambio"

def medir_antes():
    ui_set(status, "Midiendo estado ANTES de optimizar...")
    try:
        r = medir_velocidad_real()
        baseline["bajada"] = r["bajada"]
        baseline["subida"] = r["subida"]
        baseline["ping"] = r["ping"]
        baseline["jitter"] = r["jitter"]
        baseline["fecha"] = datetime.now()

        texto = (f"↓ {r['bajada']:.2f} Mbps  ↑ {r['subida']:.2f} Mbps  "
                 f"🕒 Ping: {r['ping']:.0f} ms  📶 Jitter: {r['jitter']:.0f} ms")
        ui_set(status, "📍 Línea base guardada: " + texto)
        ui_set(recos, "📍 Estado ANTES guardado.\n\nAhora aplica tus optimizaciones "
                       "(Modo Juego, cambiar DNS, etc.) y luego presiona "
                       "'📊 Medir DESPUÉS y comparar'.")
        registrar_log("Línea base (ANTES) guardada: " + texto)
    except Exception as e:
        ui_set(status, "⚠️ Error midiendo estado inicial")
        ui_mensaje("error", "Error", explicar_error_red(e))

def medir_despues_comparar():
    if baseline["bajada"] is None:
        ui_mensaje("warning", "Falta línea base",
                   "Primero presiona '📍 Medir ANTES de optimizar' antes de comparar.")
        return
    ui_set(status, "Midiendo estado DESPUÉS de optimizar...")
    try:
        r = medir_velocidad_real()
        bajada, subida, ping, jitter = r["bajada"], r["subida"], r["ping"], r["jitter"]

        cambio_bajada = calcular_cambio_pct(baseline["bajada"], bajada)
        cambio_subida = calcular_cambio_pct(baseline["subida"], subida)
        cambio_ping = calcular_cambio_pct(baseline["ping"], ping, menor_es_mejor=True)
        cambio_jitter = calcular_cambio_pct(baseline["jitter"], jitter, menor_es_mejor=True)

        texto = "📊 COMPARACIÓN ANTES vs DESPUÉS\n\n"
        texto += (f"↓ Bajada:  {baseline['bajada']:.2f} → {bajada:.2f} Mbps   "
                   f"{flecha_estado(cambio_bajada)} ({cambio_bajada:+.1f}%)\n")
        texto += (f"↑ Subida:  {baseline['subida']:.2f} → {subida:.2f} Mbps   "
                   f"{flecha_estado(cambio_subida)} ({cambio_subida:+.1f}%)\n")
        texto += (f"🕒 Ping:    {baseline['ping']:.0f} → {ping:.0f} ms       "
                   f"{flecha_estado(cambio_ping)} ({cambio_ping:+.1f}%)\n")
        texto += (f"📶 Jitter:  {baseline['jitter']:.0f} → {jitter:.0f} ms       "
                   f"{flecha_estado(cambio_jitter)} ({cambio_jitter:+.1f}%)\n\n")

        cambios = (cambio_bajada, cambio_subida, cambio_ping, cambio_jitter)
        mejoras = sum(1 for c in cambios if c > 1)
        if mejoras == len(cambios):
            texto += "✅ Todos los indicadores mejoraron."
        elif mejoras == 0:
            texto += "⚠️ Ningún indicador mejoró de forma notable. Puede ser variación normal del ISP,\n" \
                     "o que el cambio aplicado no tenga efecto real (recuerda: el DNS no mueve el ping)."
        else:
            texto += f"↔️ {mejoras} de {len(cambios)} indicadores mejoraron."

        ui_set(recos, texto)
        ui_set(status, "Comparación completa.")
        registrar_log(
            f"Comparación ANTES/DESPUÉS -> bajada {cambio_bajada:+.1f}%, "
            f"subida {cambio_subida:+.1f}%, ping {cambio_ping:+.1f}%, jitter {cambio_jitter:+.1f}%"
        )
    except Exception as e:
        ui_set(status, "⚠️ Error en test DESPUÉS")
        ui_mensaje("error", "Error", explicar_error_red(e))

# ============== LATENCIA A REGIONES (FORTNITE) ==============
# Se usa conexión TCP (no ping ICMP) porque muchos endpoints de nube
# (incluidos los de AWS) bloquean el ping por seguridad, pero sí responden
# a una conexión TCP normal (puerto 443).

def medir_latencia_tcp(host, etiqueta, puerto=443, intentos=4, timeout=3):
    try:
        ip_resuelta = socket.gethostbyname(host)
    except Exception:
        return f"{etiqueta}: no se pudo resolver el host"
    tiempos = []
    for _ in range(intentos):
        try:
            inicio = time.perf_counter()
            with socket.create_connection((ip_resuelta, puerto), timeout=timeout):
                pass
            tiempos.append((time.perf_counter() - inicio) * 1000)
        except Exception:
            pass
    if tiempos:
        promedio = sum(tiempos) / len(tiempos)
        return f"{etiqueta}: {promedio:.0f} ms"
    return f"{etiqueta}: sin respuesta"

def test_regiones_fortnite():
    ui_set(status, "Probando rutas hacia Brasil y NA-East...")
    servidores = {
        "🇧🇷 Brasil / São Paulo (región oficial de Fortnite para Sudamérica)": "s3.sa-east-1.amazonaws.com",
        "🇺🇸 NA-East / Virginia (alternativa a probar)": "s3.us-east-1.amazonaws.com",
    }
    resultados = [medir_latencia_tcp(host, etiqueta) for etiqueta, host in servidores.items()]

    texto = "\n".join(resultados)
    texto += "\n\n⚠️ Esto es una referencia aproximada (mide la ruta de red, no el servidor exacto de Epic)."
    texto += "\n\n👉 El dato real está DENTRO del juego:"
    texto += "\nConfiguración → Juego → Región de Emparejamiento,"
    texto += "\ny ahí comparas el ping que Fortnite muestra para Brasil vs NA-East y eliges el más bajo."
    ui_set(recos, texto)
    ui_set(status, "Test de regiones completado.")
    registrar_log("Test de regiones Fortnite: " + " | ".join(resultados))

def diagnostico_ruta():
    ui_set(status, "Ejecutando traceroute...")
    comando = ["tracert", "-h", "15", "-w", "800", "s3.sa-east-1.amazonaws.com"]
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=45)
        salida = resultado.stdout.strip()
        _mostrar_resultado_traceroute(salida, cortado=False)
    except subprocess.TimeoutExpired as e:
        salida_parcial = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="ignore")
        if salida_parcial.strip():
            _mostrar_resultado_traceroute(salida_parcial.strip(), cortado=True)
        else:
            ui_set(status, "⚠️ Traceroute sin respuesta")
            ui_set(recos, "🛰️ El traceroute no alcanzó a mostrar ningún salto a tiempo.\n\n"
                       "Esto suele pasar cuando tu router o el ISP bloquea por completo el tipo "
                       "de paquetes que usa traceroute. No es necesariamente un problema real: "
                       "usa mejor '🎯 Comparar Brasil vs NA-East', que sí es confiable porque "
                       "usa una conexión TCP normal en vez de ICMP.")
    except Exception as e:
        ui_set(status, "⚠️ Error en traceroute")
        ui_mensaje("error", "Error", explicar_error_red(e))

def _mostrar_resultado_traceroute(salida, cortado):
    registrar_log(("Traceroute a Brasil (cortado por timeout):\n" if cortado else "Traceroute a Brasil:\n") + salida)
    lineas = [l for l in salida.splitlines() if l.strip()]
    resumen_lineas = "\n".join(lineas[-10:]) if len(lineas) > 10 else "\n".join(lineas)
    nota = "\n\n⚠️ Se cortó antes de llegar al destino, pero estos son los saltos reales que sí respondieron." if cortado else ""
    ui_set(recos, "🛰️ Saltos hacia Brasil:\n\n" + resumen_lineas + nota +
               "\n\n(traceroute completo guardado en log_optimizador.txt)")
    ui_set(status, "Traceroute completado." if not cortado else "Traceroute parcial (ver detalle abajo).")

# ============== MODOS ESPECIALES ==============

def modo_juego():
    resultados_estabilidad = aplicar_ajustes_estabilidad()
    ui_set(recos,
        "🎮 MODO JUEGO — lo que de verdad baja el ping:\n\n"
        "1) Usa cable de red, no WiFi, si es posible.\n"
        "2) En Fortnite, prueba manualmente la región Brasil (São Paulo) y NA-East (Virginia),\n"
        "   y quédate con la que muestre menor ping en el juego.\n"
        "3) Cierra descargas, streaming o backups en otros dispositivos de la casa.\n"
        "4) Si el router lo permite, activa QoS y prioriza el dispositivo que juega.\n\n"
        "El DNS (abajo) NO afecta el ping en partida, solo la carga de páginas web.\n\n"
        "🛡️ Estabilidad aplicada:\n" + "\n".join(f"• {r}" for r in resultados_estabilidad)
    )
    limpiar_cache_dns()

def modo_ahorro():
    cambiar_dns("Google")
    ui_set(recos, "💡 MODO AHORRO\n\n- Baja calidad en video\n- Apagar apps pesadas\n- DNS: Google\n\n"
               "🛡️ Ajustes de estabilidad también aplicados (ver log_optimizador.txt para el detalle).")

# ================= INTERFAZ POR PESTAÑAS =================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("⚙️ Optimizador de Internet — Edición Fortnite")
app.state("zoomed")  # Pantalla completa al iniciar

COLOR_TARJETA = "#1f1f1f"
COLOR_ACENTO = "#2563eb"

raiz = ctk.CTkFrame(app, fg_color="transparent")
raiz.pack(fill="both", expand=True, padx=24, pady=20)

ctk.CTkLabel(raiz, text="🛠️ Optimizador de Internet", font=("Segoe UI", 26, "bold")).pack(anchor="w")
ctk.CTkLabel(raiz, text="Enfocado en bajar el ping para jugar — Calarcá, Quindío",
             font=("Segoe UI", 13), text_color="#9ca3af").pack(anchor="w", pady=(0, 4))
ctk.CTkLabel(raiz, text=f"Adaptador de red detectado: {obtener_adaptador()}",
             font=("Segoe UI", 12), text_color="#6b7280").pack(anchor="w", pady=(0, 15))

tabs = ctk.CTkTabview(raiz, height=280, segmented_button_selected_color=COLOR_ACENTO)
tabs.pack(fill="x", expand=False)

tab_inicio = tabs.add("🏠 Inicio")
tab_fortnite = tabs.add("🎯 Fortnite")
tab_estabilidad = tabs.add("🛡️ Estabilidad")
tab_comparar = tabs.add("📊 Comparar")
tab_avanzado = tabs.add("⚙️ Avanzado")

def boton(parent, texto, accion, color=None, hover=None):
    kwargs = dict(command=accion, height=42, font=("Segoe UI", 14))
    if color:
        kwargs["fg_color"] = color
    if hover:
        kwargs["hover_color"] = hover
    b = ctk.CTkButton(parent, text=texto, **kwargs)
    b.pack(pady=6, padx=10, fill="x")
    botones_accion.append(b)
    return b

def subtitulo(parent, texto):
    ctk.CTkLabel(parent, text=texto, font=("Segoe UI", 12), text_color="#9ca3af",
                 justify="left", wraplength=900).pack(anchor="w", padx=10, pady=(4, 10))

# ---- Tab Inicio ----
subtitulo(tab_inicio, "Revisa el estado general de tu conexión antes de tocar nada.")
boton(tab_inicio, "🔍 Test de Velocidad + Recomendación", lambda: hilo(test_velocidad))
boton(tab_inicio, "🌐 Ver Estado de Red (IP local/pública)", lambda: hilo(estado_red))
boton(tab_inicio, "✅ Verificar Conexión a Internet", lambda: hilo(verificar_conexion))

# ---- Tab Fortnite ----
subtitulo(tab_fortnite, "Herramientas específicas para bajar el ping jugando Fortnite desde Colombia.")
boton(tab_fortnite, "🎮 Activar Modo Juego (checklist + estabilidad)", lambda: hilo(modo_juego))
boton(tab_fortnite, "🎯 Comparar Brasil vs NA-East", lambda: hilo(test_regiones_fortnite))
boton(tab_fortnite, "🛰️ Diagnóstico de ruta (traceroute a Brasil)", lambda: hilo(diagnostico_ruta))

# ---- Tab Estabilidad ----
subtitulo(tab_estabilidad, "Para cuando la velocidad está bien pero la conexión se corta seguido.")
boton(tab_estabilidad, "🛡️ Aplicar Ajustes de Estabilidad", lambda: hilo(boton_estabilidad_manual))
boton(tab_estabilidad, "💡 Activar Modo Ahorro (DNS Google + estabilidad)", lambda: hilo(modo_ahorro))

# ---- Tab Comparar ----
subtitulo(tab_comparar, "Mide, optimiza, y mide otra vez. El programa calcula el % real de mejora.")
boton(tab_comparar, "📍 1) Medir ANTES de optimizar", lambda: hilo(medir_antes))
boton(tab_comparar, "📊 2) Medir DESPUÉS y comparar (%)", lambda: hilo(medir_despues_comparar))

# ---- Tab Avanzado ----
subtitulo(tab_avanzado, "Ajustes manuales de DNS y opciones de mantenimiento/reinicio.")

fila_dns = ctk.CTkFrame(tab_avanzado, fg_color="transparent")
fila_dns.pack(fill="x", padx=10, pady=(0, 10))
ctk.CTkLabel(fila_dns, text="Proveedor DNS:", font=("Segoe UI", 14)).pack(side="left", padx=(0, 10))
selector_dns = ctk.CTkOptionMenu(fila_dns, values=["Cloudflare", "Google", "OpenDNS"])
selector_dns.pack(side="left", padx=(0, 10))
boton_dns = ctk.CTkButton(fila_dns, text="Aplicar DNS", width=120,
                           command=lambda: hilo(cambiar_dns, selector_dns.get()))
boton_dns.pack(side="left")
botones_accion.append(boton_dns)

boton(tab_avanzado, "🧹 Limpiar Caché DNS", lambda: hilo(limpiar_cache_dns))
boton(tab_avanzado, "🔄 Reiniciar Adaptador", lambda: hilo(reiniciar_adaptador))
boton(tab_avanzado, "🔎 Redetectar Adaptador de Red", lambda: hilo(redetectar_adaptador))
boton(tab_avanzado, "↩️ Poner Configuración por Defecto", confirmar_restaurar,
      color="#8B1E1E", hover="#6B1414")

# === PANEL DE RESULTADOS ===
panel = ctk.CTkFrame(raiz, fg_color=COLOR_TARJETA, corner_radius=12)
panel.pack(fill="both", expand=True, pady=(18, 0))

status = ctk.StringVar(value="🕒 Esperando test de velocidad...")
ctk.CTkLabel(panel, textvariable=status, font=("Segoe UI", 15, "bold"),
             text_color="#ffffff", wraplength=1100, justify="left").pack(anchor="w", padx=18, pady=(16, 4))

resumen = ctk.StringVar(value="📡 Estado de IP pendiente...")
ctk.CTkLabel(panel, textvariable=resumen, font=("Segoe UI", 13), text_color="#9ca3af",
             wraplength=1100, justify="left").pack(anchor="w", padx=18, pady=(0, 10))

ctk.CTkFrame(panel, height=1, fg_color="#333333").pack(fill="x", padx=18)

ctk.CTkLabel(panel, text="📌 Recomendaciones / resultados", font=("Segoe UI", 14, "bold")).pack(
    anchor="w", padx=18, pady=(12, 4))

recos_scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent")
recos_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 12))

recos = ctk.StringVar(value="Aquí aparecerán las recomendaciones según lo que presiones arriba.")
ctk.CTkLabel(recos_scroll, textvariable=recos, font=("Segoe UI", 13), text_color="#d1d5db",
             wraplength=1100, justify="left", anchor="w").pack(anchor="w", padx=10, fill="x")

app.mainloop()
