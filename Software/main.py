import kivy
kivy.require('2.3.0')

from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty
from kivy.clock import Clock
from kivy.metrics import dp

# Importazioni per il Dialog
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton
from kivy.uix.boxlayout import BoxLayout as KivyBoxLayout 
from kivymd.uix.textfield import MDTextField

import socket
import threading
import time
from datetime import datetime

# --- CONFIGURAZIONE SOCKET GLOBALE ---
# Inizializzato a None per una gestione robusta
client = None 
IS_CONNECTED = False 
RECEIVE_TIMEOUT = 0.5 
MAX_RECEIVE_SIZE = 4096 
HANDSHAKE_TIMEOUT = 5.0 

# --- WIDGET CUSTOM PER I MESSAGGI (Chat Bubble) ---
class MessageBubble(BoxLayout):
    text = StringProperty('')
    time_str = StringProperty('')
    is_me = StringProperty('False')

# ==============================================================================
# CONTENUTO DEL POPUP DI CONNESSIONE
# ==============================================================================

class ConnectionContent(KivyBoxLayout):
    """Contenitore personalizzato per gli input all'interno del MDDialog."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.spacing = dp(15)
        self.padding = dp(15)
        self.size_hint_y = None
        self.height = dp(220) 

        # Campi Input (con la porta 55555 predefinita)
        self.nick_input = MDTextField(hint_text="Nickname", text="user")
        self.host_input = MDTextField(hint_text="Host", text="127.0.0.1")
        self.port_input = MDTextField(hint_text="Porta", text="55555") 
        
        self.add_widget(self.nick_input)
        self.add_widget(self.host_input)
        self.add_widget(self.port_input)

# ==============================================================================
# CLASSE PRINCIPALE DELL'APPLICAZIONE KIVYMD
# ==============================================================================

class KivyMDChatClient(MDApp):

    dialog = None 
    nickname = ""
    
    default_host = "127.0.0.1"
    default_port = 55555 
    default_nick = "user"
    
    receive_thread_ref = None 

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "DeepPurple" 
        return Builder.load_file('ui.kv')

    def on_start(self):
        self.show_connection_dialog()

    # ==========================================================================
    # LOGICA DEL POPUP
    # ==========================================================================
    
    def show_connection_dialog(self):
        """Crea e mostra la finestra modale per la connessione."""
        if self.dialog is None:
            self.dialog_content = ConnectionContent()
            
            self.dialog_content.nick_input.text = self.nickname or self.default_nick
            self.dialog_content.host_input.text = self.default_host
            self.dialog_content.port_input.text = str(self.default_port)

            self.dialog = MDDialog(
                title="Dati di Connessione",
                type="custom",
                content_cls=self.dialog_content,
                buttons=[
                    MDRaisedButton(
                        text="CONNETTI",
                        on_release=self.connect_and_dismiss_dialog
                    ),
                ],
            )
        
        if IS_CONNECTED:
            self.dialog.title = "Sei connesso. Disconnettersi?"
            self.dialog.buttons[0].text = "DISCONNETTI"
            self.dialog.buttons[0].on_release = lambda *args: self.disconnect()
        else:
            self.dialog.title = "Dati di Connessione"
            self.dialog.buttons[0].text = "CONNETTI"
            self.dialog.buttons[0].on_release = self.connect_and_dismiss_dialog
            
        self.dialog.open()

    def connect_and_dismiss_dialog(self, *args):
        """Legge i dati dal popup e avvia la connessione."""
        host = self.dialog_content.host_input.text
        port = self.dialog_content.port_input.text
        nickname = self.dialog_content.nick_input.text

        self.default_host = host
        self.default_nick = nickname
        try:
            self.default_port = int(port)
        except ValueError:
            self.default_port = 55555 
        
        self.dialog.dismiss()
        self.attempt_connection_from_dialog(host, port, nickname)

    def disconnect(self, *args):
        """Forza la disconnessione e aggiorna lo stato."""
        global IS_CONNECTED, client
        
        # Gestisce la chiusura in modo robusto
        if client:
            try:
                # Invia un segnale di chiusura e chiude il socket
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except Exception:
                pass 
                
        # Aggiorna lo stato globale
        was_connected = IS_CONNECTED
        IS_CONNECTED = False
            
        if was_connected:
            Clock.schedule_once(lambda dt: self.set_status_text("Disconnessione completata."))
            # Forziamo un aggiornamento UI che riaprirà il dialog
            Clock.schedule_once(lambda dt: self.update_ui_on_connect(IS_CONNECTED)) 
            
        if self.dialog:
            self.dialog.dismiss()
        
    # ==========================================================================
    # LOGICA SOCKET E HANDSHAKE
    # ==========================================================================
    
    def attempt_connection_from_dialog(self, host, port_str, nickname):
        """Valida i dati e avvia il thread di connessione."""
        global IS_CONNECTED
        if IS_CONNECTED: return

        try:
            port = int(port_str)
        except ValueError:
            self.root.ids.status_label.text = "❌ Porta non valida."
            Clock.schedule_once(lambda dt: self.show_connection_dialog(), 3)
            return
            
        if not nickname:
             self.root.ids.status_label.text = "❌ Inserisci un nickname."
             Clock.schedule_once(lambda dt: self.show_connection_dialog(), 3)
             return

        self.root.ids.status_label.text = f"Tentativo di connessione a {host}:{port} come {nickname}..."
        self.nickname = nickname
        
        threading.Thread(target=self._connection_and_handshake_thread, args=(host, port), daemon=True).start()

    def _connection_and_handshake_thread(self, host, port):
        global IS_CONNECTED, client
        error_msg = None 
        
        # --- 1. Ricreazione Socket Robusta ---
        try:
            if client: client.close()
        except:
            pass
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        try:
            # 2. Connessione TCP
            client.settimeout(3.0) 
            client.connect((host, port))
            
            # 3. Ricezione della richiesta NICK dal server (Handshake)
            client.settimeout(HANDSHAKE_TIMEOUT) 
            initial_response = client.recv(1024).decode("utf-8").strip()
            
            if initial_response != "NICK":
                raise Exception(f"Risposta server inattesa: '{initial_response}'")
                
            # 4. Invia il nickname
            client.send(self.nickname.encode("utf-8"))
            
            # 5. Verifica la risposta del server dopo l'invio del nickname
            client.settimeout(3.0) 
            
            final_response = ""
            try:
                final_response = client.recv(1024).decode("utf-8").strip()
            except socket.timeout:
                pass # Non c'era una risposta immediata, prosegui
            
            if final_response == "NICK_TAKEN":
                raise Exception(f"Nickname '{self.nickname}' già in uso.")
                
            # SUCCESS: Connessione completata
            IS_CONNECTED = True
            
            # 6. Avvia il thread di ricezione e aggiorna la UI
            self.receive_thread_ref = threading.Thread(target=self._receive_thread_logic, daemon=True)
            self.receive_thread_ref.start()
            
            # Aggiorna UI con successo
            success_msg = f"Connesso come: {self.nickname}"
            if final_response:
                success_msg += f" ({final_response})"
            
            Clock.schedule_once(lambda dt: self.set_status_text(success_msg))
            # Abilita input e bottone
            Clock.schedule_once(lambda dt: setattr(self.root.ids.msg_input, 'disabled', False))
            Clock.schedule_once(lambda dt: setattr(self.root.ids.send_btn, 'disabled', False))
            
        except ConnectionRefusedError:
             error_msg = "❌ Connessione rifiutata. Server offline o IP/Porta errati."
        except socket.timeout:
             error_msg = "❌ Timeout Handshake. Server non ha risposto in tempo."
        except socket.gaierror:
             error_msg = "❌ Indirizzo Host non valido."
        except Exception as e:
            error_msg = f"❌ Errore di connessione: {e}" 
        
        finally:
             # --- CORREZIONE WINERROR 10038 ---
             if client is not None:
                try:
                    # Tenta di rimuovere i timeout, ignorando l'errore se il socket è già chiuso.
                    client.settimeout(None)
                except Exception:
                    pass
                 
                if not IS_CONNECTED:
                    # Se non siamo connessi, chiudiamo il socket in modo pulito.
                    try: 
                        client.close()
                    except: 
                        pass

             if not IS_CONNECTED:
                # Se la connessione fallisce, aggiorna l'UI con l'errore
                Clock.schedule_once(lambda dt: self.update_ui_on_connect(IS_CONNECTED, error_msg=error_msg))
             # --- FINE CORREZIONE ---

    def update_ui_on_connect(self, connected, error_msg=None):
        """Aggiorna lo stato dei widget (chiamato dal thread Kivy)."""
        
        msg_input = self.root.ids.msg_input
        send_btn = self.root.ids.send_btn
        status_label = self.root.ids.status_label
        
        msg_input.disabled = not connected
        send_btn.disabled = not connected
        
        if connected:
            # Stato impostato nel thread di handshake
            msg_input.focus = True
        else:
            if error_msg:
                status_label.text = error_msg
                Clock.schedule_once(lambda dt: self.show_connection_dialog(), 3)
            else:
                status_label.text = "Disconnesso. Tocca per connetterti."
                self.show_connection_dialog()
            
    def set_status_text(self, text):
        self.root.ids.status_label.text = text

    def send_message(self):
        """Logica di invio del messaggio."""
        global client, IS_CONNECTED
        msg_input = self.root.ids.msg_input
        message = msg_input.text.strip()
        
        if not IS_CONNECTED or not message or client is None: return

        try:
            full_message = f"{self.nickname}: {message}"
            client.send(full_message.encode('utf-8'))
            
            self.add_message(full_message, is_me=True)
            msg_input.text = ''
        except Exception as e:
            self.add_message(f"Sistema: Errore di invio: {e}. Disconnessione forzata.")
            # Gestisce il caso di invio su socket rotto (ad esempio, server crashato)
            self.disconnect()
            
    def _receive_thread_logic(self):
        """Il thread di ricezione effettivo (non per l'handshake)."""
        global IS_CONNECTED, client
        
        while IS_CONNECTED: 
            if client is None:
                time.sleep(0.1)
                continue
                
            try:
                # Usiamo un timeout breve per non bloccare troppo il thread
                client.settimeout(RECEIVE_TIMEOUT)
                full_message_bytes = client.recv(MAX_RECEIVE_SIZE)
                
                if not full_message_bytes: 
                    # Il server ha chiuso la connessione in modo pulito
                    raise Exception("Socket chiuso dal server.")
                    
                message = full_message_bytes.decode("utf-8").strip()
                
                if message:
                    Clock.schedule_once(lambda dt, msg=message: self.add_message(msg))
                    
            except socket.timeout:
                continue
            except Exception as e:
                # Gestisce la disconnessione inaspettata
                Clock.schedule_once(lambda dt: self.add_message(f"Sistema: ❌ Disconnesso inaspettatamente. ({e})"))
                self.disconnect() # Chiude lo stato in modo pulito
                break
            finally:
                client.settimeout(None) # Rimuovi il timeout breve

    def add_message(self, message, is_me=False):
        """Aggiunge un messaggio alla lista in modo thread-safe."""
        chat_list = self.root.ids.chat_list
        timestamp = datetime.now().strftime("%H:%M")
        
        # Estrai solo il contenuto se il messaggio contiene un prefisso (es. "Nick: Messaggio")
        try:
            if ":" in message:
                 content = message.split(":", 1)[1].strip()
            else:
                content = message
        except Exception:
            content = message
        
        
        new_bubble = MessageBubble(
            text=content,
            time_str=timestamp,
            is_me=str(is_me)
        )
        
        chat_list.add_widget(new_bubble)
        
        Clock.schedule_once(lambda dt: self.scroll_to_bottom())
        
    def scroll_to_bottom(self):
        """Forza lo scroll verso l'ultimo messaggio."""
        if self.root.ids.chat_list.children:
            self.root.ids.chat_scroll.scroll_to(self.root.ids.chat_list.children[0])


if __name__ == '__main__':
    KivyMDChatClient().run()