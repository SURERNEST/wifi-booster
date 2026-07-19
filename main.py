import os
import re
import time
import threading
import subprocess
import speedtest
import requests
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

ADAPTADOR = "Wi-Fi"

# ================= FUNCIONES BASE =================

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
    messagebox.showinfo("DNS", f"DNS cambiado a {nombre}.\n\nNota: esto acelera la carga de webs, "
                                f"pero NO reduce el ping dentro de un juego online.")

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

def test_velocidad():
    status.set("Realizando test...")
    try:
        s = speedtest.Speedtest()
        s.get_best_server()
        bajada = s.download() / 1_000_000
        subida = s.upload() / 1_000_000
        ping = s.results.ping

        resultado = f"↓ {bajada:.2f} Mbps  ↑ {subida:.2f} Mbps  🕒 Ping: {ping:.0f} ms"
        registrar_log("Test velocidad: " + resultado)
        status.set(resultado)
        analizar_y_recomendar(bajada, subida, ping)
    except Exception as e:
        status.set("⚠️ Error en test")
        messagebox.showerror("Error", f"No se pudo ejecutar el test: {e}")

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

# ============== PING A REGIONES (FORTNITE) ==============

def ping_region(host, etiqueta):
    """Hace ping por consola a un host y devuelve el promedio en ms."""
    try:
        resultado = subprocess.run(
            ["ping", "-n", "4", host],
            capture_output=True, text=True, timeout=15
        )
        salida = resultado.stdout
        tiempos = re.findall(r"tiempo[=<]\s*(\d+)\s*ms", salida, re.IGNORECASE)
        if not tiempos:
            tiempos = re.findall(r"time[=<]\s*(\d+)\s*ms", salida, re.IGNORECASE)
        if tiempos:
            promedio = sum(int(t) for t in tiempos) / len(tiempos)
            return f"{etiqueta}: {promedio:.0f} ms"
        return f"{etiqueta}: sin respuesta (host podría bloquear ping)"
    except Exception as e:
        return f"{etiqueta}: error ({e})"

def test_regiones_fortnite():
    status.set("Probando rutas hacia Brasil y NA-East...")
    servidores = {
        "🇧🇷 Brasil / São Paulo (región oficial de Fortnite para Sudamérica)": "ec2.sa-east-1.amazonaws.com",
        "🇺🇸 NA-East / Virginia (alternativa a probar)": "ec2.us-east-1.amazonaws.com",
    }
    resultados = [ping_region(host, etiqueta) for etiqueta, host in servidores.items()]

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
    status.set("Ejecutando traceroute (puede tardar ~30s)...")
    try:
        resultado = subprocess.run(
            ["tracert", "-h", "20", "ec2.sa-east-1.amazonaws.com"],
            capture_output=True, text=True, timeout=60
        )
        salida = resultado.stdout.strip()
        # Guardamos el traceroute completo en el log porque es largo para mostrar en pantalla
        registrar_log("Traceroute a Brasil:\n" + salida)
        lineas = salida.splitlines()
        resumen_lineas = "\n".join(lineas[-8:]) if len(lineas) > 8 else salida
        recos.set("🛰️ Últimos saltos del traceroute hacia Brasil:\n\n" + resumen_lineas +
                   "\n\n(traceroute completo guardado en log_optimizador.txt)")
        status.set("Traceroute completado.")
    except Exception as e:
        status.set("⚠️ Error en traceroute")
        messagebox.showerror("Error", f"No se pudo ejecutar el traceroute: {e}")

# ============== MODOS ESPECIALES ==============

def modo_juego():
    recos.set(
        "🎮 MODO JUEGO — lo que de verdad baja el ping:\n\n"
        "1) Usa cable de red, no WiFi, si es posible.\n"
        "2) En Fortnite, prueba manualmente la región Brasil (São Paulo) y NA-East (Virginia),\n"
        "   y quédate con la que muestre menor ping en el juego.\n"
        "3) Cierra descargas, streaming o backups en otros dispositivos de la casa.\n"
        "4) Si el router lo permite, activa QoS y prioriza el dispositivo que juega.\n\n"
        "El DNS (abajo) NO afecta el ping en partida, solo la carga de páginas web."
    )
    limpiar_cache_dns()

def modo_ahorro():
    recos.set("💡 MODO AHORRO\n\n- Baja calidad en video\n- Apagar apps pesadas\n- DNS: Google")
    cambiar_dns("Google")

def hilo(funcion, *args):
    threading.Thread(target=lambda: funcion(*args)).start()

# ================= INTERFAZ ADAPTABLE =================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("⚙️ OPTIMIZADOR DE INTERNET PRO 3.2 — Edición Fortnite")
app.state("zoomed")  # Pantalla completa al iniciar

# === Scrollable frame para adaptarse ===
scroll_frame = ctk.CTkScrollableFrame(app)
scroll_frame.pack(padx=20, pady=20, fill="both", expand=True)

# === TITULO ===
ctk.CTkLabel(scroll_frame, text="🛠️ Optimización Inteligente de Red", font=("Segoe UI", 28, "bold")).pack(pady=20)

# === BOTONES FUNCIONALES ===

def boton_responsive(texto, accion):
    ctk.CTkButton(scroll_frame, text=texto, command=accion, height=45, font=("Segoe UI", 16)).pack(pady=8, padx=60, fill="x")

# Principales
boton_responsive("🔍 Test de Velocidad + Recomendación", lambda: hilo(test_velocidad))
boton_responsive("🌐 Ver Estado de Red", lambda: hilo(estado_red))
boton_responsive("✅ Verificar Conexión a Internet", lambda: hilo(verificar_conexion))

ctk.CTkLabel(scroll_frame, text="──────────────", font=("Segoe UI", 16)).pack(pady=10)

# Fortnite / regiones
ctk.CTkLabel(scroll_frame, text="🎯 Herramientas para bajar ping en Fortnite", font=("Segoe UI", 18, "bold")).pack(pady=(5, 10))
boton_responsive("🎯 Comparar Brasil vs NA-East", lambda: hilo(test_regiones_fortnite))
boton_responsive("🛰️ Diagnóstico de ruta (traceroute a Brasil)", lambda: hilo(diagnostico_ruta))

ctk.CTkLabel(scroll_frame, text="──────────────", font=("Segoe UI", 16)).pack(pady=10)

# Modos
boton_responsive("🎮 Activar Modo Juego", lambda: hilo(modo_juego))
boton_responsive("💡 Activar Modo Ahorro", lambda: hilo(modo_ahorro))

ctk.CTkLabel(scroll_frame, text="──────────────", font=("Segoe UI", 16)).pack(pady=10)

# Extras
boton_responsive("🧹 Limpiar Caché DNS", lambda: hilo(limpiar_cache_dns))
boton_responsive("🔄 Reiniciar Adaptador", lambda: hilo(reiniciar_adaptador))
boton_responsive("🌎 Cambiar DNS a OpenDNS", lambda: hilo(cambiar_dns, "OpenDNS"))

# === DATOS EN TIEMPO REAL ===

status = ctk.StringVar(value="🕒 Esperando test de velocidad...")
ctk.CTkLabel(scroll_frame, textvariable=status, font=("Segoe UI", 14), text_color="#cccccc", wraplength=1200, justify="center").pack(pady=10)

resumen = ctk.StringVar(value="📡 Estado de IP pendiente...")
ctk.CTkLabel(scroll_frame, textvariable=resumen, font=("Segoe UI", 13), text_color="#cccccc", wraplength=1200, justify="center").pack(pady=10)

recos = ctk.StringVar(value="📌 Aquí aparecerán recomendaciones según tu red.")
ctk.CTkLabel(scroll_frame, text="📌 Recomendaciones Inteligentes:", font=("Segoe UI", 16, "bold")).pack(pady=(20, 5))
ctk.CTkLabel(scroll_frame, textvariable=recos, font=("Segoe UI", 13), text_color="#bbbbbb", wraplength=1200, justify="left").pack(pady=10)

app.mainloop()
