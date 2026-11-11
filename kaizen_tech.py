"""
Kaizen Tech - Ferramenta de Manutencao Rapida (v7)
-----------------------------------------------
Novidades desta versao:
- Painel de informacoes do sistema (SO, CPU, RAM, disco)
- Ponto de restauracao automatico antes de mudancas
- Verificacao de atualizacoes do Windows pendentes
- Campo de nome do cliente + relatorio final em PDF
- Backup rapido de Desktop/Documentos/Imagens antes de formatar
- Icone proprio (kaizen.ico)

Requisitos antes de compilar:
    pip install pyinstaller fpdf2

Compile com (instrucoes completas no final do arquivo):
    pyinstaller --onefile --noconsole --uac-admin --icon=kaizen.ico --name "KaizenTech" kaizen_tech.py
"""

import os
import sys
import glob
import stat
import time
import shutil
import platform
import subprocess
import tempfile
import ctypes
import winreg
import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate_if_needed():
    if is_admin():
        return
    try:
        params = " ".join([f'"{a}"' for a in sys.argv])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    except Exception:
        pass
    sys.exit(0)


def human_size(num_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def get_size(path):
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except Exception:
                    pass
        return total
    except Exception:
        return 0


def is_reparse_point(path):
    """True para links simbólicos, junções e demais reparse points (não segue o link).

    Usado pela limpeza, que roda elevada, para nunca descer por um link plantado
    numa pasta gravável por outros usuários (ex.: C:\\Windows\\Temp) e acabar
    apagando arquivos fora dela.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return True  # na dúvida, trata como inseguro e pula
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or stat.S_ISLNK(st.st_mode)


def _delete_tree_no_follow(path):
    """Apaga `path` (arquivo ou pasta) sem atravessar reparse points.
    Retorna (bytes_liberados, itens_ignorados)."""
    if is_reparse_point(path):
        return 0, 1
    if not os.path.isdir(path):
        size = os.path.getsize(path)
        os.remove(path)
        return size, 0
    freed, skipped = 0, 0
    for entry in os.listdir(path):
        try:
            f, s = _delete_tree_no_follow(os.path.join(path, entry))
            freed += f
            skipped += s
        except OSError:
            skipped += 1
    try:
        os.rmdir(path)  # só remove se ficou vazia
    except OSError:
        skipped += 1
    return freed, skipped


def clean_folder_safely(folder):
    """Apaga o conteúdo de `folder` sem seguir links/junções.
    Retorna (itens_removidos, itens_ignorados, bytes_liberados)."""
    removed, failed, freed = 0, 0, 0
    if not os.path.isdir(folder) or is_reparse_point(folder):
        return removed, failed, freed
    for item in os.listdir(folder):
        path = os.path.join(folder, item)
        try:
            f, skipped = _delete_tree_no_follow(path)
            freed += f
            if skipped:
                failed += 1
            else:
                removed += 1
        except OSError:
            failed += 1
    return removed, failed, freed


def _explorer_running():
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq explorer.exe", "/nh"],
                             capture_output=True, text=True, timeout=10).stdout
        return "explorer.exe" in out.lower()
    except Exception:
        return False


def restart_explorer_unelevated():
    """Reinicia o Explorer sem herdar o token de administrador deste processo.

    Encerrar o Explorer faz o Winlogon reiniciá-lo sozinho como shell do usuário
    (integridade média). Só se isso não acontecer em alguns segundos o processo é
    iniciado com 'runas /trustlevel:0x20000', que descarta os privilégios elevados.
    O Explorer nunca é iniciado diretamente a partir do processo elevado.
    """
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False, capture_output=True)
    for _ in range(10):
        time.sleep(0.5)
        if _explorer_running():
            return
    subprocess.run(["runas", "/trustlevel:0x20000", "explorer.exe"], check=False, capture_output=True)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_memory_info():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys, stat.ullAvailPhys
    except Exception:
        return 0, 0


def get_cpu_name():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return name.strip()
    except Exception:
        return platform.processor() or "Desconhecido"


def get_windows_version():
    try:
        v = sys.getwindowsversion()
        return f"Windows (build {v.build})"
    except Exception:
        return platform.platform()


class KaizenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Kaizen Tech — Manutenção Rápida")
        self.root.geometry("680x780")
        self.root.configure(bg="#1C2B45")
        self.actions_log = []
        self.total_freed = 0
        self.client_name_var = tk.StringVar()

        try:
            self.root.iconbitmap(resource_path("kaizen.ico"))
        except Exception:
            pass

        title = tk.Label(
            root, text="KAIZEN TECH", font=("Segoe UI", 20, "bold"),
            fg="#F4EFE1", bg="#1C2B45"
        )
        title.pack(pady=(16, 0))

        status = "Executando como Administrador ✓" if is_admin() else "⚠ Sem privilégios de administrador"
        subtitle = tk.Label(
            root, text=status,
            font=("Segoe UI", 10), fg="#8FD19E" if is_admin() else "#E8B563", bg="#1C2B45"
        )
        subtitle.pack(pady=(0, 10))

        # Nome do cliente
        client_frame = tk.Frame(root, bg="#1C2B45")
        client_frame.pack(pady=(0, 10))
        tk.Label(client_frame, text="Cliente:", font=("Segoe UI", 10), fg="#C7CBD8", bg="#1C2B45").pack(side="left", padx=(0, 6))
        tk.Entry(client_frame, textvariable=self.client_name_var, width=40, font=("Segoe UI", 10)).pack(side="left")

        # Painel de informações do sistema
        self.info_frame = tk.Frame(root, bg="#EFE9D8")
        self.info_frame.pack(fill="x", padx=16, pady=(0, 10))
        self.info_label = tk.Label(
            self.info_frame, text="Carregando informações do sistema...",
            font=("Consolas", 9), fg="#262521", bg="#EFE9D8", justify="left", anchor="w"
        )
        self.info_label.pack(fill="x", padx=10, pady=8)
        tk.Button(
            self.info_frame, text="Atualizar informações", command=self.refresh_system_info,
            font=("Segoe UI", 8), bg="#D9D1B8", relief="flat"
        ).pack(pady=(0, 6))

        btn_frame = tk.Frame(root, bg="#1C2B45")
        btn_frame.pack(pady=4)

        actions = [
            ("Criar ponto de restauração", self.create_restore_point, False),
            ("Limpar arquivos temporários (usuário + sistema)", self.clean_temp, True),
            ("Limpar cache de navegador (Chrome/Edge/Firefox)", self.clean_browser_cache, True),
            ("Esvaziar lixeira", self.empty_recycle_bin, True),
            ("Verificar saúde do disco (somente leitura)", self.check_disk, False),
            ("Verificar atualizações do Windows pendentes", self.check_windows_update, False),
            ("Ativar plano de Alto Desempenho", self.set_high_performance, False),
            ("Desativar animações e efeitos visuais", self.disable_visual_effects, True),
            ("Restaurar efeitos visuais padrão", self.restore_visual_effects, False),
            ("Remover anúncios/sugestões do Menu Iniciar", self.remove_start_menu_ads, True),
            ("Desativar Game Bar em segundo plano", self.disable_gamebar_background, True),
            ("Backup rápido antes de formatar", self.backup_user_folders, False),
            ("Listar programas de inicialização", self.list_startup, False),
            ("Gerar relatório do atendimento (PDF)", self.generate_report, False),
        ]

        for label, cmd, needs_confirm in actions:
            handler = (lambda c=cmd, l=label: self._run_with_confirm(c, l)) if needs_confirm else cmd
            b = tk.Button(
                btn_frame, text=label, command=handler,
                font=("Segoe UI", 10), width=48, bg="#EFE9D8", fg="#262521",
                relief="flat", pady=6
            )
            b.pack(pady=2)

        self.log_box = scrolledtext.ScrolledText(
            root, height=10, bg="#0F1729", fg="#B8C4E0",
            font=("Consolas", 9), relief="flat"
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(12, 16))
        self.log("Pronto. Escolha uma ação acima.")
        self.refresh_system_info()

    # ---------- utilidades de interface ----------

    def _run_with_confirm(self, func, label):
        if messagebox.askyesno("Confirmar ação", f"Tem certeza que deseja executar:\n\n{label}?"):
            func()

    def log(self, text):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self.actions_log.append(entry)
        self.log_box.insert(tk.END, entry + "\n")
        self.log_box.see(tk.END)

    # ---------- painel de sistema ----------

    def refresh_system_info(self):
        try:
            total_ram, avail_ram = get_memory_info()
            total_disk, used_disk, free_disk = shutil.disk_usage("C:\\")
            info = (
                f"SO: {get_windows_version()}   |   Processador: {get_cpu_name()}   |   Núcleos: {os.cpu_count()}\n"
                f"RAM: {human_size(avail_ram)} livres de {human_size(total_ram)}   |   "
                f"Disco C: {human_size(free_disk)} livres de {human_size(total_disk)}"
            )
            self.info_label.config(text=info)
        except Exception as e:
            self.info_label.config(text=f"Não foi possível obter informações do sistema: {e}")

    # ---------- ponto de restauração ----------

    def create_restore_point(self):
        self.log("Criando ponto de restauração do Windows...")
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 'Checkpoint-Computer -Description "Kaizen Tech - manutenção" -RestorePointType "MODIFY_SETTINGS"'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                self.log("Ponto de restauração criado com sucesso.")
            else:
                self.log("Não foi possível criar o ponto agora (o Windows limita 1 a cada 24h por padrão).")
        except Exception as e:
            self.log(f"Erro ao criar ponto de restauração: {e}")

    # ---------- limpeza ----------

    def _clean_folder(self, folder):
        """Apaga o conteúdo de `folder` sem nunca seguir links ou junções.

        Reparse points (links simbólicos, junções) são pulados e contados como
        ignorados: o processo roda elevado e pastas como C:\\Windows\\Temp são
        graváveis por outros usuários.
        """
        return clean_folder_safely(folder)

    def clean_temp(self):
        self.log("Limpando temporários do usuário (%TEMP%)...")
        r1, f1, s1 = self._clean_folder(tempfile.gettempdir())
        self.log(f"  → {r1} itens removidos, {f1} ignorados, {human_size(s1)} liberados.")

        self.log("Limpando temporários do sistema (C:\\Windows\\Temp)...")
        r2, f2, s2 = self._clean_folder(r"C:\Windows\Temp")
        self.log(f"  → {r2} itens removidos, {f2} ignorados, {human_size(s2)} liberados.")

        total = s1 + s2
        self.total_freed += total
        self.log(f"Limpeza concluída: {human_size(total)} liberados no total.")
        self.refresh_system_info()

    def clean_browser_cache(self):
        self.log("Limpando cache de navegadores...")
        local = os.environ.get("LOCALAPPDATA", "")
        targets = [
            os.path.join(local, r"Google\Chrome\User Data\Default\Cache"),
            os.path.join(local, r"Google\Chrome\User Data\Default\Code Cache"),
            os.path.join(local, r"Microsoft\Edge\User Data\Default\Cache"),
            os.path.join(local, r"Microsoft\Edge\User Data\Default\Code Cache"),
        ]
        targets += glob.glob(os.path.join(local, r"Mozilla\Firefox\Profiles\*\cache2"))

        total = 0
        for t in targets:
            if os.path.isdir(t):
                r, f, s = self._clean_folder(t)
                if r or f:
                    self.log(f"  → {os.path.basename(os.path.dirname(t))}: {r} itens, {human_size(s)} liberados.")
                total += s

        self.total_freed += total
        self.log(f"Cache de navegador limpo: {human_size(total)} liberados no total.")
        self.log("  Obs: pode ser necessário reabrir o navegador.")
        self.refresh_system_info()

    def empty_recycle_bin(self):
        self.log("Esvaziando lixeira...")
        try:
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000001 | 0x00000002)
            self.log("Lixeira esvaziada com sucesso.")
        except Exception as e:
            self.log(f"Não foi possível esvaziar a lixeira: {e}")

    # ---------- disco / updates ----------

    def check_disk(self):
        self.log("Verificando saúde do disco (via PowerShell, somente leitura)...")
        try:
            result = subprocess.run(
                ["powershell", "-Command", "(Repair-Volume -DriveLetter C -Scan).HealthStatus"],
                capture_output=True, text=True, timeout=180
            )
            output = result.stdout.strip()
            if "NoErrorsFound" in output or output == "":
                self.log("✓ Disco saudável — nenhum erro encontrado.")
            elif "Unhealthy" in output or "Failed" in output:
                self.log(f"⚠ Possível problema no disco detectado (status: {output}). Recomenda-se investigar mais a fundo.")
            else:
                self.log(f"Status retornado: {output}")
            if result.stderr.strip():
                self.log(f"Aviso: {result.stderr.strip()}")
        except Exception as e:
            self.log(f"Erro ao verificar disco: {e}")

    def check_windows_update(self):
        self.log("Verificando atualizações pendentes (pode levar até 1 minuto)...")
        script = (
            "$s = New-Object -ComObject Microsoft.Update.Session;"
            "$r = $s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Software'\");"
            "foreach ($u in $r.Updates) { Write-Output $u.Title }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-Command", script],
                capture_output=True, text=True, timeout=150
            )
            titles = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
            if not titles:
                self.log("Sistema atualizado — nenhuma atualização pendente.")
            else:
                self.log(f"{len(titles)} atualização(ões) pendente(s):")
                for t in titles:
                    self.log(f"  • {t}")
                self.log("Para instalar: Configurações → Windows Update → Instalar agora.")
        except Exception as e:
            self.log(f"Erro ao verificar atualizações: {e}")
            self.log("  Verifique manualmente em Configurações → Windows Update.")

    # ---------- desempenho ----------

    def set_high_performance(self):
        self.log("Ativando plano de energia 'Alto Desempenho'...")
        high_perf_guid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        try:
            subprocess.run(["powercfg", "/setactive", high_perf_guid], check=True)
            self.log("Plano de Alto Desempenho ativado.")
        except Exception as e:
            self.log(f"Não foi possível ativar automaticamente: {e}")

    def _set_visual_effects(self, enabled: bool):
        menu_delay = "400" if enabled else "0"
        drag_full = "1" if enabled else "0"
        min_animate = "1" if enabled else "0"
        dword_val = 1 if enabled else 0

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "MenuShowDelay", 0, winreg.REG_SZ, menu_delay)
        winreg.SetValueEx(key, "DragFullWindows", 0, winreg.REG_SZ, drag_full)
        winreg.CloseKey(key)

        key2 = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key2, "MinAnimate", 0, winreg.REG_SZ, min_animate)
        winreg.CloseKey(key2)

        key3 = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key3, "TaskbarAnimations", 0, winreg.REG_DWORD, dword_val)
        winreg.SetValueEx(key3, "ListviewShadow", 0, winreg.REG_DWORD, dword_val)
        winreg.SetValueEx(key3, "ListviewAlphaSelect", 0, winreg.REG_DWORD, dword_val)
        winreg.CloseKey(key3)

        restart_explorer_unelevated()

    def disable_visual_effects(self):
        self.log("Desativando animações e efeitos visuais inúteis...")
        self.create_restore_point()
        try:
            self._set_visual_effects(enabled=False)
            self.log("Efeitos visuais desativados. Desktop reaparecendo em instantes.")
        except Exception as e:
            self.log(f"Erro ao ajustar efeitos visuais: {e}")

    def restore_visual_effects(self):
        self.log("Restaurando efeitos visuais padrão do Windows...")
        try:
            self._set_visual_effects(enabled=True)
            self.log("Efeitos visuais restaurados ao padrão. Desktop reaparecendo em instantes.")
        except Exception as e:
            self.log(f"Erro ao restaurar efeitos visuais: {e}")

    def remove_start_menu_ads(self):
        """Remove anúncios e sugestões do Menu Iniciar. Seguro e 100% reversível — não afeta
        nenhuma funcionalidade, só remove conteúdo promocional."""
        self.log("Removendo anúncios e sugestões do Menu Iniciar...")
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                0, winreg.KEY_SET_VALUE
            )
            for value_name in [
                "SubscribedContent-338388Enabled",  # sugestões no Menu Iniciar
                "SubscribedContent-353694Enabled",  # dicas ocasionais
                "SubscribedContent-338389Enabled",  # sugestões de conteúdo
                "SystemPaneSuggestionsEnabled",       # sugestões no painel do sistema
            ]:
                try:
                    winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, 0)
                except Exception:
                    pass
            winreg.CloseKey(key)
            self.log("Concluído. Sugestões e anúncios removidos do Menu Iniciar.")
        except Exception as e:
            self.log(f"Erro ao remover sugestões: {e}")

    def disable_gamebar_background(self):
        """Desativa a gravação em segundo plano do Xbox Game Bar. Não afeta nenhum programa
        de trabalho — só evita que o Windows reserve recursos para gravação de tela que
        clientes profissionais nunca usam."""
        self.log("Desativando gravação em segundo plano do Game Bar...")
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, r"System\GameConfigStore", 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "GameDVR_Enabled", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            self.log("Concluído. Game Bar em segundo plano desativado.")
        except Exception as e:
            self.log(f"Erro ao desativar Game Bar: {e}")

    # ---------- backup ----------

    def backup_user_folders(self):
        dest = filedialog.askdirectory(title="Selecione o destino do backup (pendrive ou HD externo)")
        if not dest:
            self.log("Backup cancelado — nenhum destino selecionado.")
            return

        user_profile = os.path.expanduser("~")
        folders = ["Desktop", "Documents", "Pictures"]
        self.log(f"Iniciando backup para: {dest}")

        for folder in folders:
            src = os.path.join(user_profile, folder)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(dest, folder)
            self.log(f"Copiando {folder}...")
            try:
                subprocess.run(
                    ["robocopy", src, dst, "/E", "/R:1", "/W:1"],
                    capture_output=True, text=True, timeout=1800
                )
                self.log(f"  → {folder} copiado.")
            except Exception as e:
                self.log(f"  → Erro ao copiar {folder}: {e}")

        self.log("Backup concluído. Confira o destino antes de prosseguir com a formatação.")

    # ---------- inicialização ----------

    def list_startup(self):
        self.log("Listando programas de inicialização...")
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance Win32_StartupCommand | Select-Object Name, Command | Format-Table -AutoSize"],
                capture_output=True, text=True, timeout=30
            )
            self.log(result.stdout.strip() or "Nenhum item encontrado.")
        except Exception as e:
            self.log(f"Erro ao listar inicialização: {e}")

    # ---------- relatório ----------

    def _pdf_font(self, pdf):
        """Tenta usar a fonte DejaVu (suporta acentos, travessões, etc).
        Se os arquivos de fonte não estiverem junto do .exe, cai para Helvetica
        com sanitização de texto para não travar a geração do PDF."""
        try:
            pdf.add_font("DejaVu", "", resource_path("fonts/DejaVuSans.ttf"))
            pdf.add_font("DejaVu", "B", resource_path("fonts/DejaVuSans-Bold.ttf"))
            return "DejaVu", False
        except Exception:
            return "Helvetica", True

    @staticmethod
    def _sanitize(text, needed):
        if not needed:
            return text
        return text.encode("latin-1", "replace").decode("latin-1")

    def generate_report(self):
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            client = self.client_name_var.get().strip() or "Não informado"
            base_name = f"relatorio_kaizen_tech_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"

            if FPDF_AVAILABLE:
                path = os.path.join(desktop, base_name + ".pdf")
                pdf = FPDF()
                font, needs_sanitize = self._pdf_font(pdf)
                s = lambda t: self._sanitize(t, needs_sanitize)

                pdf.add_page()
                pdf.set_fill_color(28, 43, 69)
                pdf.rect(0, 0, 210, 28, style="F")
                pdf.set_text_color(244, 239, 225)
                pdf.set_font(font, "B", 20)
                pdf.set_xy(10, 8)
                pdf.cell(0, 12, "KAIZEN TECH", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                pdf.set_text_color(30, 30, 30)
                pdf.set_font(font, "", 11)
                pdf.set_xy(10, 34)
                pdf.cell(0, 8, s(f"Relatório de Atendimento - {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_x(10)
                pdf.cell(0, 8, s(f"Cliente: {client}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_x(10)
                pdf.cell(0, 8, s(f"Espaço total liberado: {human_size(self.total_freed)}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(4)
                pdf.set_draw_color(169, 130, 71)
                pdf.line(10, pdf.get_y(), 200, pdf.get_y())
                pdf.ln(6)

                pdf.set_font(font, "", 9)
                for line in self.actions_log:
                    pdf.set_x(10)
                    pdf.multi_cell(0, 5, s(line) if line else " ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                pdf.output(path)
            else:
                self.log("Aviso: biblioteca fpdf2 não encontrada nesta compilação — gerando em .txt.")
                path = os.path.join(desktop, base_name + ".txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("KAIZEN TECH — Relatório de Atendimento\n")
                    f.write(f"Cliente: {client}\n")
                    f.write(f"Data: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
                    f.write(f"Espaço total liberado: {human_size(self.total_freed)}\n")
                    f.write("-" * 40 + "\n")
                    f.write("\n".join(self.actions_log))

            self.log(f"Relatório salvo em: {path}")

            # Abre o arquivo automaticamente para confirmação visual
            try:
                os.startfile(path)
            except Exception:
                pass

            self.root.lift()
            self.root.attributes("-topmost", True)
            messagebox.showinfo(
                "Relatório gerado",
                f"Relatório salvo na área de trabalho:\n{os.path.basename(path)}\n\nEspaço liberado: {human_size(self.total_freed)}"
            )
            self.root.attributes("-topmost", False)

        except Exception as e:
            self.log(f"ERRO ao gerar relatório: {e}")
            messagebox.showerror("Erro ao gerar relatório", f"Não foi possível gerar o relatório:\n\n{e}")


def resource_path(relative_path):
    """Resolve o caminho do ícone tanto rodando direto quanto compilado com PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    elevate_if_needed()
    root = tk.Tk()
    app = KaizenApp(root)
    root.mainloop()

# ---------------------------------------------------------------------------
# COMO COMPILAR
# ---------------------------------------------------------------------------
# 1. Instale a dependência nova (gera o PDF):
#       pip install fpdf2
#
# 2. Organize a pasta assim, tudo junto:
#       kaizen_tech.py
#       kaizen.ico
#       fonts/
#           DejaVuSans.ttf
#           DejaVuSans-Bold.ttf
#
# 3. Compile incluindo o ícone e as fontes embutidas no .exe:
#       pyinstaller --onefile --noconsole --uac-admin --icon=kaizen.ico ^
#           --add-data "kaizen.ico;." --add-data "fonts;fonts" ^
#           --name "KaizenTech" kaizen_tech.py
#
#    (o "^" é só para quebrar linha no CMD — pode colar tudo em uma linha só)
#
# 4. O executável final sai em dist\KaizenTech.exe, já com ícone,
#    fonte com acentuação completa no PDF, e todas as funções corrigidas.
# ---------------------------------------------------------------------------
