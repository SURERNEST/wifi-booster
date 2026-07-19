import os
import re
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

ADAPTADOR = "Wi-Fi"

# ================= FUNCIONES BASE =================

def restaurar_configuracion_por_defecto():
    confirmar = messagebox.askyesno(
        "Restaurar configuración por defecto",
        "Esto va a:\n\n"
        "• Volver el DNS a automático (el que asigna tu proveedor de Internet)\n"
        "• Limpiar la caché de DNS\n"
        "• Reiniciar el adaptador de red\n\n"
        "Es decir, deja la red como estaba antes de usar este programa.\n\n¿Continuar?"
    )
    if not confirmar:
        return

    os.system(f'netsh interface ip set dns name="{ADAPTADOR}" dhcp')
    os.system(f'netsh interface ipv6 set dns name="{ADAPTADOR}" dhcp')
    os.system("ipconfig /flushdns")

    # Revertir el ahorro de energía a su estado original (Windows lo trae
    # habilitado por defecto de fábrica).
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

    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=disable')
    time.sleep(3)
    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=enable')

    registrar_log("Configuración de red restaurada a valores por defecto (DNS automático, ahorro de energía habilitado)")
    messagebox.showinfo(
        "Restaurado",
        "✅ La red quedó como estaba antes: DNS automático, caché limpia y adaptador reiniciado."
    )
    recos.set("🔁 Configuración de red restaurada a los valores originales del sistema (DNS automático por DHCP).")

# ============== ESTABILIDAD (no solo velocidad) ==============
# Estos ajustes no atacan la velocidad, atacan los CORTES/picos de ping
# intermitentes, que suelen tener otra causa distinta a la velocidad bruta.
# Se ejecutan automáticamente dentro de cada botón de "optimizar"
# (Modo Juego, Modo Ahorro, Cambiar DNS) para que no haya que acordarse
# de aplicarlos aparte. Todo queda igual registrado en el log.

def aplicar_ajustes_estabilidad():
    resultados = []

    # 1) Desactivar el ahorro de energía del adaptador de red.
    #    Es una causa MUY común de "se corta la wifi cada rato" aunque
    #    la velocidad medida esté perfecta: Windows apaga brevemente el
    #    radio del adaptador para ahorrar batería/energía.
    try:
        ps_cmd = (
            'powershell -NoProfile -Command '
            '"Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
            'ForEach-Object { Set-NetAdapterPowerManagement -Name $_.Name '
            '-AllowComputerToTurnOffDevice Disabled -ErrorAction SilentlyContinue }"'
        )
        subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=20)
        resultados.append("Ahorro de energía del adaptador desactivado")
    except Exception as e:
        resultados.append(f"Ahorro de energía: no se pudo ajustar ({e})")

    # 2) Normalizar el auto-tuning de TCP. Muchos routers baratos de ISP
    #    tienen bugs con el "window scaling" de Windows, lo que causa
    #    micro-cortes y picos de ping aleatorios. Ponerlo en "normal"
    #    (el valor recomendado por Microsoft) evita ese conflicto.
    try:
        os.system("netsh interface tcp set global autotuninglevel=normal")
        resultados.append("Auto-tuning TCP normalizado")
    except Exception as e:
        resultados.append(f"TCP autotuning: no se pudo ajustar ({e})")

    # 3) Renovar el lease de IP del adaptador. Si el router entregó una IP
    #    vieja o hay conflicto de direcciones, esto suele arreglar cortes
    #    intermitentes sin tener que reiniciar el router físicamente.
    try:
        os.system(f'ipconfig /release "{ADAPTADOR}" > nul 2>&1')
        time.sleep(1)
        os.system(f'ipconfig /renew "{ADAPTADOR}" > nul 2>&1')

        # Esperar a que la red vuelva a responder antes de devolver el
        # control. Sin esto, si el usuario corre un test justo después,
        # falla con "getaddrinfo failed" porque la IP todavía se está
        # renegociando (esto es lo que te pasó en el test anterior).
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
    recos.set(
        "🛡️ Ajustes de estabilidad aplicados:\n\n" + "\n".join(f"• {r}" for r in resultados) +
        "\n\nEsto ataca los CORTES intermitentes, no la velocidad. "
        "Si el problema es que 'anda rápido pero se cae', esto es lo que hay que probar."
    )

def cambiar_dns(nombre):
    dns_opciones = {
        "Cloudflare": ("1.1.1.1", "1.0.0.1"),
        "Google": ("8.8.8.8", "8.8.4.4"),
        "OpenDNS": ("208.67.222.222", "208.67.220.220")
    }
    dns1, dns2 = dns_opciones[nombre]
    os.system(f'netsh interface ip set dns name="{ADAPTADOR}" static {dns1}')
    os.system(f'netsh interface ip add dns name="{ADAPTADOR}" {dns2} index=2')
    registrar_log(f"DNS cambiado a {nombre}")
    aplicar_ajustes_estabilidad()
    messagebox.showinfo("DNS", f"DNS cambiado a {nombre}.\n\nNota: esto acelera la carga de webs, "
                                f"pero NO reduce el ping dentro de un juego online.\n\n"
                                f"También se aplicaron ajustes de estabilidad (ahorro de energía, "
                                f"TCP y renovación de IP) para reducir cortes intermitentes.")

def limpiar_cache_dns():
    os.system("ipconfig /flushdns")
    registrar_log("Caché DNS limpiado")
    messagebox.showinfo("DNS", "Caché DNS limpiado.")

def reiniciar_adaptador():
    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=disable')
    time.sleep(3)
    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=enable')
    registrar_log("Adaptador de red reiniciado")
    messagebox.showinfo("Red", "Adaptador reiniciado.")

def registrar_log(mensaje):
    with open("log_optimizador.txt", "a", encoding="utf-8") as log:
        log.write(f"{datetime.now()} - {mensaje}\n")

def explicar_error_red(e):
    """Traduce errores técnicos comunes de red a un mensaje entendible."""
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

def estado_red():
    try:
        ip_local = os.popen("ipconfig").read().split("IPv4")[1].split(":")[1].split("\n")[0].strip()
    except Exception:
        ip_local = "No encontrada"
    try:
        ip_publica = requests.get("https://api.ipify.org", timeout=5).text
    except Exception:
        ip_publica = "No disponible"
    resumen.set(f"📶 IP Local: {ip_local}\n🌍 IP Pública: {ip_publica}")
    registrar_log("Estado de red consultado")

def verificar_conexion():
    try:
        requests.get("https://www.google.com", timeout=2)
        registrar_log("Conexión verificada: OK")
        messagebox.showinfo("Conexión", "✅ Tienes acceso a Internet.")
    except Exception:
        registrar_log("Conexión verificada: SIN ACCESO")
        messagebox.showwarning("Conexión", "❌ No tienes acceso a Internet.")

# ============== TEST + RECOMENDACIONES ==============
# No usamos la librería "speedtest-cli": lleva años sin actualizarse y
# Ookla cambió su sistema, por eso daba 403 Forbidden sin importar cuántas
# veces se reintentara. En su lugar medimos directo contra los endpoints
# públicos de Cloudflare (los mismos que usa speed.cloudflare.com), que
# son estables y no dependen de una librería externa desactualizada.

CF_DOWN = "https://speed.cloudflare.com/__down"
CF_UP = "https://speed.cloudflare.com/__up"

def medir_velocidad_real(bytes_bajada=40_000_000, bytes_subida=10_000_000, reintentos=2):
    """Mide ping (TCP), bajada y subida reales. Reintenta automáticamente
    si hay una falla transitoria de red (por eso 'reintentos=2')."""
    ultimo_error = None
    for intento in range(1, reintentos + 1):
        try:
            # --- Ping real por TCP contra el borde de Cloudflare ---
            tiempos_ping = []
            for _ in range(4):
                try:
                    inicio = time.perf_counter()
                    with socket.create_connection(("speed.cloudflare.com", 443), timeout=4):
                        pass
                    tiempos_ping.append((time.perf_counter() - inicio) * 1000)
                except Exception:
                    pass
            if not tiempos_ping:
                raise RuntimeError("No se pudo medir ping (sin respuesta del servidor)")
            ping = sum(tiempos_ping) / len(tiempos_ping)

            # --- Bajada real ---
            inicio = time.perf_counter()
            total_descargado = 0
            r = requests.get(f"{CF_DOWN}?bytes={bytes_bajada}", stream=True, timeout=25)
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=131072):
                total_descargado += len(chunk)
            duracion_bajada = time.perf_counter() - inicio
            if duracion_bajada <= 0 or total_descargado == 0:
                raise RuntimeError("La descarga de prueba no trajo datos")
            bajada = (total_descargado * 8) / duracion_bajada / 1_000_000  # Mbps

            # --- Subida real ---
            datos_subida = os.urandom(bytes_subida)
            inicio = time.perf_counter()
            r = requests.post(CF_UP, data=datos_subida, timeout=25)
            r.raise_for_status()
            duracion_subida = time.perf_counter() - inicio
            if duracion_subida <= 0:
                raise RuntimeError("La subida de prueba no se completó")
            subida = (bytes_subida * 8) / duracion_subida / 1_000_000  # Mbps

            return {"bajada": bajada, "subida": subida, "ping": ping}

        except Exception as e:
            ultimo_error = e
            if intento < reintentos:
                time.sleep(2)  # pausa corta antes de reintentar solo
                continue
    raise ultimo_error

def test_velocidad():
    status.set("Realizando test...")
    try:
        r = medir_velocidad_real()
        resultado = f"↓ {r['bajada']:.2f} Mbps  ↑ {r['subida']:.2f} Mbps  🕒 Ping: {r['ping']:.0f} ms"
        registrar_log("Test velocidad: " + resultado)
        status.set(resultado)
        analizar_y_recomendar(r["bajada"], r["subida"], r["ping"])
    except Exception as e:
        status.set("⚠️ Error en test")
        messagebox.showerror("Error", explicar_error_red(e))

def analizar_y_recomendar(bajada, subida, ping):
    recomendaciones = []
    if bajada < 10:
        recomendaciones.append("🔁 Velocidad de bajada baja. Considera hablar con tu ISP.")
    if subida < 3:
        recomendaciones.append("📤 Subida limitada. Evita apps como Drive/streaming mientras juegas.")
    if ping > 100:
        recomendaciones.append("🐢 Ping alto hacia el servidor de test. Revisa apps en 2do plano y usa cable.")
    if not recomendaciones:
        recomendaciones.append("✅ Conexión óptima.")

    recos.set("\n".join(recomendaciones))
    registrar_log("Recomendaciones generadas.")

# ============== COMPARACIÓN ANTES / DESPUÉS ==============
# Guarda una "línea base" (velocidad y ping actuales) y luego, tras aplicar
# los cambios (DNS, modo juego, etc.), vuelve a medir y calcula el % real
# de mejora o empeoramiento de cada métrica. Todo con datos reales del
# speedtest, no valores inventados.

baseline = {"bajada": None, "subida": None, "ping": None, "fecha": None}

def calcular_cambio_pct(antes, despues, menor_es_mejor=False):
    """Devuelve el % de cambio. Si menor_es_mejor=True (caso del ping),
    una bajada en el valor se reporta como % positivo (mejora)."""
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
    status.set("Midiendo estado ANTES de optimizar...")
    try:
        r = medir_velocidad_real()
        baseline["bajada"] = r["bajada"]
        baseline["subida"] = r["subida"]
        baseline["ping"] = r["ping"]
        baseline["fecha"] = datetime.now()

        texto = f"↓ {r['bajada']:.2f} Mbps  ↑ {r['subida']:.2f} Mbps  🕒 Ping: {r['ping']:.0f} ms"
        status.set("📍 Línea base guardada: " + texto)
        recos.set("📍 Estado ANTES guardado.\n\nAhora aplica tus optimizaciones "
                   "(Modo Juego, cambiar DNS, etc.) y luego presiona "
                   "'📊 Medir DESPUÉS y comparar'.")
        registrar_log("Línea base (ANTES) guardada: " + texto)
    except Exception as e:
        status.set("⚠️ Error midiendo estado inicial")
        messagebox.showerror("Error", explicar_error_red(e))

def medir_despues_comparar():
    if baseline["bajada"] is None:
        messagebox.showwarning(
            "Falta línea base",
            "Primero presiona '📍 Medir ANTES de optimizar' antes de comparar."
        )
        return
    status.set("Midiendo estado DESPUÉS de optimizar...")
    try:
        r = medir_velocidad_real()
        bajada, subida, ping = r["bajada"], r["subida"], r["ping"]

        cambio_bajada = calcular_cambio_pct(baseline["bajada"], bajada)
        cambio_subida = calcular_cambio_pct(baseline["subida"], subida)
        cambio_ping = calcular_cambio_pct(baseline["ping"], ping, menor_es_mejor=True)

        texto = "📊 COMPARACIÓN ANTES vs DESPUÉS\n\n"
        texto += (f"↓ Bajada:  {baseline['bajada']:.2f} → {bajada:.2f} Mbps   "
                   f"{flecha_estado(cambio_bajada)} ({cambio_bajada:+.1f}%)\n")
        texto += (f"↑ Subida:  {baseline['subida']:.2f} → {subida:.2f} Mbps   "
                   f"{flecha_estado(cambio_subida)} ({cambio_subida:+.1f}%)\n")
        texto += (f"🕒 Ping:    {baseline['ping']:.0f} → {ping:.0f} ms       "
                   f"{flecha_estado(cambio_ping)} ({cambio_ping:+.1f}%)\n\n")

        mejoras = sum(1 for c in (cambio_bajada, cambio_subida, cambio_ping) if c > 1)
        if mejoras == 3:
            texto += "✅ Los 3 indicadores mejoraron."
        elif mejoras == 0:
            texto += "⚠️ Ningún indicador mejoró de forma notable. Puede ser variación normal del ISP,\n" \
                     "o que el cambio aplicado no tenga efecto real (recuerda: el DNS no mueve el ping)."
        else:
            texto += f"↔️ {mejoras} de 3 indicadores mejoraron."

        recos.set(texto)
        status.set("Comparación completa.")
        registrar_log(
            f"Comparación ANTES/DESPUÉS -> bajada {cambio_bajada:+.1f}%, "
            f"subida {cambio_subida:+.1f}%, ping {cambio_ping:+.1f}%"
        )
    except Exception as e:
        status.set("⚠️ Error en test DESPUÉS")
        messagebox.showerror("Error", explicar_error_red(e))

# ============== LATENCIA A REGIONES (FORTNITE) ==============
# Nota: usamos conexión TCP (no ping ICMP) porque muchos endpoints de nube
# (incluidos los de AWS) bloquean el ping por seguridad, pero sí responden
# a una conexión TCP normal (puerto 443). Esto da timeouts falsos con ping
# aunque el programa se ejecute como administrador; el problema no es de
# permisos, es que el host no contesta a ICMP.

def medir_latencia_tcp(host, etiqueta, puerto=443, intentos=4, timeout=3):
    tiempos = []
    for _ in range(intentos):
        try:
            inicio = time.perf_counter()
            with socket.create_connection((host, puerto), timeout=timeout):
                pass
            tiempos.append((time.perf_counter() - inicio) * 1000)
        except Exception:
            pass
    if tiempos:
        promedio = sum(tiempos) / len(tiempos)
        return f"{etiqueta}: {promedio:.0f} ms"
    return f"{etiqueta}: sin respuesta"

def test_regiones_fortnite():
    status.set("Probando rutas hacia Brasil y NA-East...")
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
    recos.set(texto)
    status.set("Test de regiones completado.")
    registrar_log("Test de regiones Fortnite: " + " | ".join(resultados))

def diagnostico_ruta():
    """Traceroute hacia São Paulo para ver en qué salto se dispara la latencia."""
    status.set("Ejecutando traceroute...")
    # -h 15: máximo 15 saltos.  -w 800: 800ms de espera por sonda en vez de
    # los 4000ms por defecto de Windows. Con eso el peor caso teórico es
    # 15 saltos x 3 sondas x 0.8s ≈ 36s, en vez de poder llegar a los 3 min
    # que tardaba antes y disparaba el timeout de 60s que viste.
    comando = ["tracert", "-h", "15", "-w", "800", "s3.sa-east-1.amazonaws.com"]
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=45)
        salida = resultado.stdout.strip()
        _mostrar_resultado_traceroute(salida, cortado=False)
    except subprocess.TimeoutExpired as e:
        # Aunque se corte por timeout, Windows ya alcanzó a mandar la salida
        # parcial de los saltos que sí completó — la aprovechamos en vez de
        # descartarla, así el usuario ve algo útil en lugar de un error seco.
        salida_parcial = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="ignore")
        if salida_parcial.strip():
            _mostrar_resultado_traceroute(salida_parcial.strip(), cortado=True)
        else:
            status.set("⚠️ Traceroute sin respuesta")
            recos.set("🛰️ El traceroute no alcanzó a mostrar ningún salto a tiempo.\n\n"
                       "Esto suele pasar cuando tu router o el ISP bloquea por completo el tipo "
                       "de paquetes que usa traceroute. No es necesariamente un problema real: "
                       "usa mejor '🎯 Comparar Brasil vs NA-East', que sí es confiable porque "
                       "usa una conexión TCP normal en vez de ICMP.")
    except Exception as e:
        status.set("⚠️ Error en traceroute")
        messagebox.showerror("Error", explicar_error_red(e))

def _mostrar_resultado_traceroute(salida, cortado):
    registrar_log(("Traceroute a Brasil (cortado por timeout):\n" if cortado else "Traceroute a Brasil:\n") + salida)
    lineas = [l for l in salida.splitlines() if l.strip()]
    resumen_lineas = "\n".join(lineas[-10:]) if len(lineas) > 10 else "\n".join(lineas)
    nota = "\n\n⚠️ Se cortó antes de llegar al destino, pero estos son los saltos reales que sí respondieron." if cortado else ""
    recos.set("🛰️ Saltos hacia Brasil:\n\n" + resumen_lineas + nota +
               "\n\n(traceroute completo guardado en log_optimizador.txt)")
    status.set("Traceroute completado." if not cortado else "Traceroute parcial (ver detalle abajo).")

# ============== MODOS ESPECIALES ==============

def modo_juego():
    resultados_estabilidad = aplicar_ajustes_estabilidad()
    recos.set(
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
    # cambiar_dns ya aplica los ajustes de estabilidad internamente,
    # así que no los repetimos aquí (evita frenar la red dos veces seguidas).
    cambiar_dns("Google")
    recos.set("💡 MODO AHORRO\n\n- Baja calidad en video\n- Apagar apps pesadas\n- DNS: Google\n\n"
               "🛡️ Ajustes de estabilidad también aplicados (ver log_optimizador.txt para el detalle).")

def hilo(funcion, *args):
    threading.Thread(target=lambda: funcion(*args)).start()

# ================= INTERFAZ POR PESTAÑAS =================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("⚙️ Optimizador de Internet — Edición Fortnite")
app.state("zoomed")  # Pantalla completa al iniciar

COLOR_TARJETA = "#1f1f1f"
COLOR_ACENTO = "#2563eb"

# === Contenedor raíz ===
raiz = ctk.CTkFrame(app, fg_color="transparent")
raiz.pack(fill="both", expand=True, padx=24, pady=20)

# === TÍTULO ===
ctk.CTkLabel(raiz, text="🛠️ Optimizador de Internet", font=("Segoe UI", 26, "bold")).pack(anchor="w")
ctk.CTkLabel(raiz, text="Enfocado en bajar el ping para jugar — Calarcá, Quindío",
             font=("Segoe UI", 13), text_color="#9ca3af").pack(anchor="w", pady=(0, 15))

# === PESTAÑAS ===
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
    ctk.CTkButton(parent, text=texto, **kwargs).pack(pady=6, padx=10, fill="x")

def subtitulo(parent, texto):
    ctk.CTkLabel(parent, text=texto, font=("Segoe UI", 12), text_color="#9ca3af",
                 justify="left", wraplength=900).pack(anchor="w", padx=10, pady=(4, 10))

# ---- Tab Inicio: diagnóstico general ----
subtitulo(tab_inicio, "Revisa el estado general de tu conexión antes de tocar nada.")
boton(tab_inicio, "🔍 Test de Velocidad + Recomendación", lambda: hilo(test_velocidad))
boton(tab_inicio, "🌐 Ver Estado de Red (IP local/pública)", lambda: hilo(estado_red))
boton(tab_inicio, "✅ Verificar Conexión a Internet", lambda: hilo(verificar_conexion))

# ---- Tab Fortnite: lo que de verdad importa para el ping en el juego ----
subtitulo(tab_fortnite, "Herramientas específicas para bajar el ping jugando Fortnite desde Colombia.")
boton(tab_fortnite, "🎮 Activar Modo Juego (checklist + estabilidad)", lambda: hilo(modo_juego))
boton(tab_fortnite, "🎯 Comparar Brasil vs NA-East", lambda: hilo(test_regiones_fortnite))
boton(tab_fortnite, "🛰️ Diagnóstico de ruta (traceroute a Brasil)", lambda: hilo(diagnostico_ruta))

# ---- Tab Estabilidad: cortes intermitentes ----
subtitulo(tab_estabilidad, "Para cuando la velocidad está bien pero la conexión se corta seguido.")
boton(tab_estabilidad, "🛡️ Aplicar Ajustes de Estabilidad", lambda: hilo(boton_estabilidad_manual))
boton(tab_estabilidad, "💡 Activar Modo Ahorro (DNS Google + estabilidad)", lambda: hilo(modo_ahorro))

# ---- Tab Comparar: antes/después ----
subtitulo(tab_comparar, "Mide, optimiza, y mide otra vez. El programa calcula el % real de mejora.")
boton(tab_comparar, "📍 1) Medir ANTES de optimizar", lambda: hilo(medir_antes))
boton(tab_comparar, "📊 2) Medir DESPUÉS y comparar (%)", lambda: hilo(medir_despues_comparar))

# ---- Tab Avanzado: DNS manual, limpieza, reset ----
subtitulo(tab_avanzado, "Ajustes manuales de DNS y opciones de mantenimiento/reinicio.")

fila_dns = ctk.CTkFrame(tab_avanzado, fg_color="transparent")
fila_dns.pack(fill="x", padx=10, pady=(0, 10))
ctk.CTkLabel(fila_dns, text="Proveedor DNS:", font=("Segoe UI", 14)).pack(side="left", padx=(0, 10))
selector_dns = ctk.CTkOptionMenu(fila_dns, values=["Cloudflare", "Google", "OpenDNS"])
selector_dns.pack(side="left", padx=(0, 10))
ctk.CTkButton(fila_dns, text="Aplicar DNS", width=120,
              command=lambda: hilo(cambiar_dns, selector_dns.get())).pack(side="left")

boton(tab_avanzado, "🧹 Limpiar Caché DNS", lambda: hilo(limpiar_cache_dns))
boton(tab_avanzado, "🔄 Reiniciar Adaptador", lambda: hilo(reiniciar_adaptador))
boton(tab_avanzado, "↩️ Poner Configuración por Defecto", lambda: hilo(restaurar_configuracion_por_defecto),
      color="#8B1E1E", hover="#6B1414")

# === PANEL DE RESULTADOS (siempre visible debajo de las pestañas) ===
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
