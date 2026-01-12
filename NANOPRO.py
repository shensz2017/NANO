import sys
import traceback
import os
import json

# --- 1. 启动环境检查与崩溃捕获 ---
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import threading
    import base64
    import time
    from datetime import datetime
    from concurrent.futures import ThreadPoolExecutor
except ImportError as e:
    with open("crash_log.txt", "w", encoding="utf-8") as f:
        f.write(f"启动失败，缺少库文件: {str(e)}\n\n完整报错:\n{traceback.format_exc()}")
    sys.exit(1)
except Exception as e:
    with open("crash_log.txt", "w", encoding="utf-8") as f:
        f.write(f"启动失败，发生未知错误: {str(e)}\n\n完整报错:\n{traceback.format_exc()}")
    sys.exit(1)

# ================= 2. 配置常量 =================
BASE_URL = "https://api.grsai.com"
SUBMIT_PATH = "/v1/draw/nano-banana"
RESULT_PATH = "/v1/draw/result"
CONFIG_FILE = "config.json" # 配置文件路径

# !!! 最大并发数量配置 !!!
MAX_WORKERS = 30  
# !!! 提交间隔 (秒) - 错峰提交 !!!
SUBMIT_DELAY = 0.5 

MODEL_OPTIONS = ["nano-banana-fast", "nano-banana", "nano-banana-pro", "nano-banana-pro-vt"]
RATIO_OPTIONS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]
SIZE_OPTIONS = ["1K", "2K", "4K"] 

# ================= 3. 网络会话管理 =================
def create_session():
    """创建一个带有重试机制和连接池的Session"""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# ================= 4. UI 组件类 =================
class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, background="#ffffff")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, padding=5)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

# ================= 5. 主程序类 =================
class NanoBananaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Nano Banana Pro - 全功能增强版 (MAX: {MAX_WORKERS})")
        self.root.geometry("1150x900")
        
        # 变量
        self.api_key_var = tk.StringVar()
        self.save_path_var = tk.StringVar(value=os.path.join(os.getcwd(), "outputs"))
        self.model_var = tk.StringVar(value="nano-banana-fast")
        self.ratio_var = tk.StringVar(value="auto")
        self.size_var = tk.StringVar(value="1K")
        
        # 批量模式变量
        self.batch_mode_var = tk.StringVar(value="img_folder") # img_folder, txt_folder, count_loop
        self.batch_count_var = tk.IntVar(value=10) # 纯计数模式的数量
        
        # 任务管理
        self.batch_data = [] 
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.active_tasks_count = 0
        self.lock = threading.Lock()
        
        # 全局Session
        self.session = create_session()

        # 加载配置
        self.load_config()
        
        self.setup_ui()

    def load_config(self):
        """读取本地配置文件"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                    self.api_key_var.set(conf.get("api_key", ""))
                    # 也可以保存上次的路径等，这里只演示Key
            except Exception as e:
                print(f"配置文件读取失败: {e}")

    def save_config(self):
        """保存配置到本地"""
        try:
            conf = {"api_key": self.api_key_var.get().strip()}
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(conf, f)
        except Exception as e:
            print(f"配置文件保存失败: {e}")

    def setup_ui(self):
        # --- 顶部配置 ---
        config_frame = ttk.LabelFrame(self.root, text="API与参数", padding=10)
        config_frame.pack(fill="x", padx=10, pady=5)

        row1 = ttk.Frame(config_frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="API Key:").pack(side="left")
        ttk.Entry(row1, textvariable=self.api_key_var, width=35).pack(side="left", padx=5)
        ttk.Label(row1, text="保存路径:").pack(side="left", padx=(15, 0))
        ttk.Entry(row1, textvariable=self.save_path_var, width=25).pack(side="left", padx=5)
        ttk.Button(row1, text="选择", command=self.select_save_path, width=6).pack(side="left")

        row2 = ttk.Frame(config_frame)
        row2.pack(fill="x", pady=5)
        ttk.Label(row2, text="模型:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.model_var, values=MODEL_OPTIONS, state="readonly", width=18).pack(side="left", padx=5)
        ttk.Label(row2, text="比例:").pack(side="left", padx=(10,0))
        ttk.Combobox(row2, textvariable=self.ratio_var, values=RATIO_OPTIONS, state="readonly", width=8).pack(side="left", padx=5)
        ttk.Label(row2, text="分辨率:").pack(side="left", padx=(10,0))
        ttk.Combobox(row2, textvariable=self.size_var, values=SIZE_OPTIONS, state="readonly", width=6).pack(side="left", padx=5)

        # --- 选项卡 ---
        tab_control = ttk.Notebook(self.root)
        tab_control.pack(expand=1, fill="both", padx=10, pady=5)

        self.tab_batch = ttk.Frame(tab_control)
        tab_control.add(self.tab_batch, text="批量任务 (推荐)")
        self.setup_batch_tab()

        self.tab_single = ttk.Frame(tab_control)
        tab_control.add(self.tab_single, text="单任务 (调试用)")
        self.setup_single_tab()

        # --- 日志 ---
        log_frame = ttk.LabelFrame(self.root, text="系统日志 (实时)", padding=5)
        log_frame.pack(fill="x", padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        
        # 底部状态
        status_bar = ttk.Frame(self.root, padding=(10, 5))
        status_bar.pack(fill="x")
        self.global_status_label = ttk.Label(status_bar, text=f"就绪 (最大并发: {MAX_WORKERS})")
        self.global_status_label.pack(side="left")

    def setup_single_tab(self):
        frame = ttk.Frame(self.tab_single, padding=10)
        frame.pack(fill="both", expand=True)
        
        img_frame = ttk.LabelFrame(frame, text="1. 参考图片 (可选，留空即为文生图)", padding=5)
        img_frame.pack(fill="x", pady=5)
        self.single_files_listbox = tk.Listbox(img_frame, height=4)
        self.single_files_listbox.pack(fill="x", pady=5)
        btn_bar = ttk.Frame(img_frame)
        btn_bar.pack(anchor="w")
        ttk.Button(btn_bar, text="添加图片", command=self.add_single_images).pack(side="left", padx=5)
        ttk.Button(btn_bar, text="清空列表", command=lambda: self.single_files_listbox.delete(0, tk.END)).pack(side="left")

        prompt_frame = ttk.LabelFrame(frame, text="2. 提示词", padding=5)
        prompt_frame.pack(fill="both", expand=True, pady=5)
        self.single_prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4)
        self.single_prompt_text.pack(fill="both", expand=True)

        ttk.Button(frame, text="开始单任务执行", command=self.start_single_task).pack(pady=10, fill="x")

    def setup_batch_tab(self):
        frame = ttk.Frame(self.tab_batch, padding=10)
        frame.pack(fill="both", expand=True)

        # 模式选择区域
        mode_frame = ttk.LabelFrame(frame, text="1. 选择批量模式", padding=10)
        mode_frame.pack(fill="x", pady=5)
        
        ttk.Radiobutton(mode_frame, text="文件夹图片 (Img2Img)", variable=self.batch_mode_var, value="img_folder", command=self.on_batch_mode_change).pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="文件夹TXT (文生图批量)", variable=self.batch_mode_var, value="txt_folder", command=self.on_batch_mode_change).pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="指定数量 (文生图循环)", variable=self.batch_mode_var, value="count_loop", command=self.on_batch_mode_change).pack(side="left", padx=10)

        # 动态输入区域
        self.input_container = ttk.Frame(frame)
        self.input_container.pack(fill="x", pady=5)
        
        # 初始化显示文件夹选择器
        self.setup_folder_input()

        # 批量工具
        tool_frame = ttk.LabelFrame(frame, text="批量提示词工具", padding=5)
        tool_frame.pack(fill="x", pady=5)
        self.global_prompt_var = tk.StringVar()
        ttk.Entry(tool_frame, textvariable=self.global_prompt_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(tool_frame, text="填充空缺", command=lambda: self.batch_fill_prompts(False)).pack(side="left", padx=2)
        ttk.Button(tool_frame, text="强制覆盖", command=lambda: self.batch_fill_prompts(True)).pack(side="left", padx=2)

        # 列表
        list_container = ttk.LabelFrame(frame, text="任务队列", padding=2)
        list_container.pack(fill="both", expand=True, pady=5)
        header = ttk.Frame(list_container)
        header.pack(fill="x", padx=5)
        ttk.Label(header, text="任务名 / 文件名", width=30, font=("bold")).pack(side="left")
        ttk.Label(header, text="提示词", font=("bold")).pack(side="left", padx=5)
        ttk.Label(header, text="状态 / 操作", width=15, anchor="e", font=("bold")).pack(side="right", padx=20)

        self.list_frame = ScrollableFrame(list_container)
        self.list_frame.pack(fill="both", expand=True)

        ttk.Button(frame, text="启动批量任务 (自动保存Key)", command=self.start_batch_tasks).pack(fill="x", pady=5)

    def setup_folder_input(self):
        """动态构建输入UI - 文件夹选择器"""
        for widget in self.input_container.winfo_children(): widget.destroy()
        
        ttk.Label(self.input_container, text="输入文件夹:").pack(side="left")
        self.batch_folder_var = tk.StringVar()
        ttk.Entry(self.input_container, textvariable=self.batch_folder_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(self.input_container, text="加载列表", command=self.load_batch_folder).pack(side="left")

    def setup_count_input(self):
        """动态构建输入UI - 数量选择器"""
        for widget in self.input_container.winfo_children(): widget.destroy()
        
        ttk.Label(self.input_container, text="生成数量:").pack(side="left")
        ttk.Spinbox(self.input_container, from_=1, to=1000, textvariable=self.batch_count_var, width=10).pack(side="left", padx=5)
        ttk.Button(self.input_container, text="生成列表", command=self.generate_count_list).pack(side="left")

    def on_batch_mode_change(self):
        """当模式切换时更新UI"""
        mode = self.batch_mode_var.get()
        if mode == "count_loop":
            self.setup_count_input()
        else:
            self.setup_folder_input()
        
        # 清空列表
        for widget in self.list_frame.scrollable_frame.winfo_children(): widget.destroy()
        self.batch_data = []

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def select_save_path(self):
        path = filedialog.askdirectory()
        if path: self.save_path_var.set(path)

    def add_single_images(self):
        files = filedialog.askopenfilenames(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")])
        for f in files: self.single_files_listbox.insert(tk.END, f)

    def generate_count_list(self):
        """循环模式：生成 N 个空任务"""
        count = self.batch_count_var.get()
        self.batch_data = []
        for widget in self.list_frame.scrollable_frame.winfo_children(): widget.destroy()
        
        prompt_text = self.global_prompt_var.get() # 默认取工具栏里的提示词
        
        for i in range(count):
            task_name = f"Batch_Task_{i+1:03d}"
            
            row = ttk.Frame(self.list_frame.scrollable_frame)
            row.pack(fill="x", pady=2, padx=5)

            ttk.Label(row, text=task_name, width=30, anchor="w").pack(side="left")
            prompt_var = tk.StringVar(value=prompt_text)
            ttk.Entry(row, textvariable=prompt_var).pack(side="left", fill="x", expand=True, padx=5)

            status_frame = ttk.Frame(row, width=100)
            status_frame.pack(side="right")
            status_label = ttk.Label(status_frame, text="等待", width=12, anchor="e")
            status_label.pack(fill="both")

            item_data = {
                "type": "count_loop",
                "filename": task_name,
                "prompt_var": prompt_var,
                "status_label": status_label,
                "status_frame": status_frame,
                "row_widget": row,
                "retry_btn": None,
                "path": None # 无路径
            }
            self.batch_data.append(item_data)
        self.log(f"已创建 {count} 个文生图任务，请填写提示词或直接开始。")

    def load_batch_folder(self):
        mode = self.batch_mode_var.get()
        folder = filedialog.askdirectory()
        if not folder: return
        self.batch_folder_var.set(folder)
        
        for widget in self.list_frame.scrollable_frame.winfo_children(): widget.destroy()
        self.batch_data = []

        files = []
        if mode == "img_folder":
            files = [f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        elif mode == "txt_folder":
            files = [f for f in os.listdir(folder) if f.lower().endswith('.txt')]

        if not files:
            messagebox.showinfo("提示", "该文件夹下没有匹配的文件")
            return

        self.log(f"加载文件夹: {len(files)} 个文件 (模式: {mode})")

        for filename in files:
            file_path = os.path.join(folder, filename)
            initial_prompt = ""
            
            # 读取逻辑
            if mode == "img_folder":
                txt_path = os.path.splitext(file_path)[0] + ".txt"
                if os.path.exists(txt_path):
                    try: 
                        with open(txt_path,'r',encoding='utf-8') as f: initial_prompt = f.read().strip()
                    except: pass
            elif mode == "txt_folder":
                # 直接读自己
                try: 
                    with open(file_path,'r',encoding='utf-8') as f: initial_prompt = f.read().strip()
                except: pass

            row = ttk.Frame(self.list_frame.scrollable_frame)
            row.pack(fill="x", pady=2, padx=5)

            ttk.Label(row, text=filename, width=30, anchor="w").pack(side="left")
            prompt_var = tk.StringVar(value=initial_prompt)
            ttk.Entry(row, textvariable=prompt_var).pack(side="left", fill="x", expand=True, padx=5)

            status_frame = ttk.Frame(row, width=100)
            status_frame.pack(side="right")
            status_label = ttk.Label(status_frame, text="等待", width=12, anchor="e")
            status_label.pack(fill="both")

            item_data = {
                "type": mode,
                "path": file_path,
                "filename": filename,
                "prompt_var": prompt_var,
                "status_label": status_label,
                "status_frame": status_frame,
                "row_widget": row,
                "retry_btn": None
            }
            self.batch_data.append(item_data)

    def batch_fill_prompts(self, overwrite):
        text = self.global_prompt_var.get().strip()
        if not text: return
        count = 0
        for item in self.batch_data:
            if overwrite or not item["prompt_var"].get().strip():
                item["prompt_var"].set(text)
                count += 1
        self.log(f"填充了 {count} 条提示词")

    def image_to_base64(self, path):
        if not path or not os.path.exists(path): return None
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
                ext = os.path.splitext(path)[1].lower()
                mime = "image/jpeg" if ext in ['.jpg','.jpeg'] else "image/png"
                return f"data:{mime};base64,{b64}"
        except Exception as e:
            self.log(f"读取图片失败 {path}: {e}")
            return None

    def download_image(self, url, prefix):
        save_dir = self.save_path_var.get()
        if not os.path.exists(save_dir): os.makedirs(save_dir)
        try:
            resp = self.session.get(url, stream=True, timeout=60)
            if resp.status_code == 200:
                fname = f"{prefix}_{int(time.time())}.png"
                fpath = os.path.join(save_dir, fname)
                with open(fpath, 'wb') as f:
                    for chunk in resp.iter_content(1024): f.write(chunk)
                return True
        except Exception as e:
            self.log(f"下载出错: {e}")
        return False

    def start_single_task(self):
        # 保存 Key
        self.save_config()
        
        api_key = self.api_key_var.get().strip()
        prompt = self.single_prompt_text.get("1.0", tk.END).strip()
        urls = self.single_files_listbox.get(0, tk.END)
        
        if not api_key or not prompt:
            messagebox.showerror("错误", "API Key和提示词必填")
            return
        
        config = {
            "model": self.model_var.get(),
            "ratio": self.ratio_var.get(),
            "size": self.size_var.get()
        }
        
        # 判断是否为纯文生图
        url_list = list(urls) if urls else []
        
        task_info = {
            "type": "single",
            "prompt": prompt,
            "urls": url_list,
            "filename": "SingleTask",
            "ui_item": None
        }
        self.log(f"启动单任务... ({'图生图' if url_list else '文生图'})")
        self.executor.submit(self.process_task_thread, task_info, api_key, config)

    def start_batch_tasks(self):
        self.save_config() # 自动保存Key
        
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("错误", "请输入API Key")
            return
        if not self.batch_data: return
        
        current_config = {
            "model": self.model_var.get(),
            "ratio": self.ratio_var.get(),
            "size": self.size_var.get()
        }
        
        self.log(f"准备提交 {len(self.batch_data)} 个任务...")
        threading.Thread(target=self._submit_batch_slowly, args=(api_key, current_config)).start()

    def _submit_batch_slowly(self, api_key, config):
        count = 0
        for item in self.batch_data:
            p = item["prompt_var"].get().strip()
            if not p:
                self.update_ui_status(item, "跳过(无词)", "gray")
                continue
            
            self.reset_ui_item(item)
            
            # 确定 urls
            target_urls = []
            # 只有模式为 img_folder 时才去读取图片
            if item["type"] == "img_folder" and item["path"]:
                target_urls = [item["path"]]
            
            task_info = {
                "type": item["type"],
                "prompt": p,
                "urls": target_urls, # 文生图模式下这里为空
                "filename": item["filename"],
                "ui_item": item
            }
            
            self.executor.submit(self.process_task_thread, task_info, api_key, config)
            count += 1
            time.sleep(SUBMIT_DELAY)
        
        self.log(f"所有任务已进入后台队列。")

    def reset_ui_item(self, item):
        self.root.after(0, lambda: self._reset_ui_item_sync(item))

    def _reset_ui_item_sync(self, item):
        if item["retry_btn"]:
            item["retry_btn"].pack_forget()
        item["status_label"].pack(fill="both")
        item["status_label"].config(text="排队中...", foreground="black")

    def show_retry_button(self, item, task_info, api_key, config):
        def on_retry():
            self.log(f"手动重试: {item['filename']}")
            self.reset_ui_item(item)
            self.executor.submit(self.process_task_thread, task_info, api_key, config)

        item["status_label"].pack_forget()
        if not item["retry_btn"]:
            item["retry_btn"] = ttk.Button(item["status_frame"], text="重试", command=on_retry)
        else:
            item["retry_btn"].configure(command=on_retry)
        item["retry_btn"].pack(fill="both")

    def update_ui_status(self, item, text, color="black"):
        if item:
            self.root.after(0, lambda: item["status_label"].config(text=text, foreground=color))

    def process_task_thread(self, task, api_key, config):
        """核心处理逻辑"""
        with self.lock:
            self.active_tasks_count += 1
            self.root.after(0, lambda: self.global_status_label.config(text=f"运行中... (活跃: {self.active_tasks_count})"))

        item = task.get("ui_item")
        filename = task.get("filename")
        
        # 准备图片 (如果有)
        processed_urls = []
        if task.get("urls"):
            for p in task["urls"]:
                b64 = self.image_to_base64(p)
                if b64: processed_urls.append(b64)
                else: self.log(f"⚠️ {filename} 图片读取失败")
            
            # 如果是图生图模式却没读到图，报错
            if not processed_urls and task["type"] == "img_folder":
                 self.log(f"❌ {filename} 失败: 图片数据为空")
                 self.update_ui_status(item, "图片错误", "red")
                 with self.lock: self.active_tasks_count -= 1
                 return

        payload = {
            "model": config["model"], 
            "prompt": task["prompt"],
            "aspectRatio": config["ratio"],
            "imageSize": config["size"],
            "webHook": "-1",
            "shutProgress": False
        }
        # 只有当确实有图片时才传 urls，否则就是纯文生图
        if processed_urls: payload["urls"] = processed_urls
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        max_retries = 1
        success = False
        
        for attempt in range(max_retries + 1):
            if attempt > 0:
                self.log(f"{filename} -> 自动重试第 {attempt} 次...")
                self.update_ui_status(item, f"重试{attempt}...", "orange")
            else:
                self.update_ui_status(item, "提交中...", "blue")

            try:
                resp = self.session.post(BASE_URL + SUBMIT_PATH, headers=headers, json=payload, timeout=40)
                rj = resp.json()
                
                if rj.get("code") != 0:
                    raise Exception(f"API Error: {rj.get('msg')}")
                
                task_id = rj.get("data", {}).get("id")
                if not task_id: raise Exception("No Task ID")

                self.update_ui_status(item, "生成 0%", "blue")
                while True:
                    time.sleep(1.5)
                    c_resp = self.session.post(BASE_URL + RESULT_PATH, headers=headers, json={"id": task_id}, timeout=30)
                    cj = c_resp.json()
                    
                    if cj.get("code") == 0:
                        data = cj.get("data", {})
                        status = data.get("status")
                        prog = data.get("progress", 0)
                        
                        self.update_ui_status(item, f"生成 {prog}%", "blue")
                        
                        if status == "succeeded":
                            prefix = os.path.splitext(filename)[0]
                            # 如果是纯循环模式，名字可能会重复，加个随机数
                            if task.get("type") == "count_loop":
                                prefix = f"{filename}_{int(time.time()*1000)%10000}"
                            
                            for res in data.get("results", []):
                                self.download_image(res["url"], prefix)
                            success = True
                            break
                        elif status == "failed":
                            reason = data.get('failure_reason', 'Unknown')
                            raise Exception(f"Server Failed: {reason}")
                    else:
                        raise Exception("Check Status Error")
                
                if success: break

            except Exception as e:
                self.log(f"{filename} 错误: {str(e)}")
                time.sleep(2)
        
        with self.lock:
            self.active_tasks_count -= 1
            if self.active_tasks_count == 0:
                self.root.after(0, lambda: self.global_status_label.config(text="队列空闲"))
            else:
                self.root.after(0, lambda: self.global_status_label.config(text=f"运行中... (活跃: {self.active_tasks_count})"))

        if success:
            self.update_ui_status(item, "完成", "green")
            self.log(f"{filename} 完成")
        else:
            self.log(f"{filename} 失败")
            if item:
                self.root.after(0, lambda: self.show_retry_button(item, task, api_key, config))

# ================= 5. 程序入口 =================
if __name__ == "__main__":
    try:
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass

        root = tk.Tk()
        app = NanoBananaApp(root)
        root.mainloop()

    except Exception as e:
        with open("crash_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n运行时严重错误:\n{traceback.format_exc()}")