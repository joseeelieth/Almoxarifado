from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "chave_secreta_almoxarifado"
DATABASE = "banco.db"

# ================= CONTEXTO GLOBAL (JINJA) =================
@app.context_processor
def inject_datetime():
    return dict(datetime=datetime)

# ================= FUNÇÕES DE BANCO =================
def conectar():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ================= CRIAÇÃO DO BANCO =================
def criar_banco():
    conn = conectar()
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # ================= USUÁRIOS =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        cpf TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK (perfil IN ('ADM','OPERADOR'))
    )
    """)

    # ================= PRODUTOS =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        descricao TEXT,
        tamanho TEXT,
        peso_unitario REAL DEFAULT 0,
        peso_total REAL DEFAULT 0,
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ================= ESTOQUE =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        setor TEXT NOT NULL,
        quantidade REAL NOT NULL DEFAULT 0,
        peso REAL NOT NULL DEFAULT 0,
        atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (produto_id, setor),
        FOREIGN KEY (produto_id)
            REFERENCES produtos(id)
            ON DELETE CASCADE
    )
    """)

    # ================= MOVIMENTOS (LOG GERAL) =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        produto_id INTEGER NOT NULL,
        de_setor TEXT,
        para_setor TEXT,
        quantidade REAL DEFAULT 0,
        peso REAL DEFAULT 0,
        usuario_id INTEGER,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= ENTRADAS =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS entradas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        setor TEXT NOT NULL,
        quantidade REAL,
        peso REAL,
        data TEXT,
        usuario_id INTEGER,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= SAÍDAS =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saidas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        setor TEXT NOT NULL,
        quantidade REAL,
        peso REAL,
        data TEXT,
        usuario_id INTEGER,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= TRANSFERÊNCIAS =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transferencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        de_setor TEXT NOT NULL,
        para_setor TEXT NOT NULL,
        quantidade REAL,
        peso REAL,
        data TEXT,
        usuario_id INTEGER,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= AJUSTES DE SALDO =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ajustes_saldo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        setor TEXT NOT NULL,
        quantidade REAL,
        peso REAL,
        usuario_id INTEGER,
        data TEXT,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= NOVOS PRODUTOS (LOG) =================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS relatorio_novos_produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        setor TEXT NOT NULL,
        usuario_id INTEGER,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (produto_id) REFERENCES produtos(id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )
    """)

    # ================= USUÁRIO ADM PADRÃO =================
    total = cursor.execute(
        "SELECT COUNT(*) FROM usuarios"
    ).fetchone()[0]

    if total == 0:
        cursor.execute("""
        INSERT INTO usuarios (nome, email, cpf, senha, perfil)
        VALUES (?, ?, ?, ?, ?)
        """, (
            "Administrador",
            "admin@admin.com",
            "00000000000",
            generate_password_hash("admin123"),
            "ADM"
        ))

    conn.commit()
    conn.close()

    print("✅ Banco criado com sucesso")

# ================= FUNÇÃO PARA REGISTRAR MOVIMENTOS =================
def conectar():
    import sqlite3
    # Timeout de 10s e permite múltiplas threads (Flask)
    db = sqlite3.connect("banco.db", timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def registrar_movimento(db, tipo, produto_id, setor_origem=None, setor_destino=None,
                        quantidade=0, peso=0, usuario_id=None):
    """
    Registra movimentos no banco de dados e atualiza o estoque.
    Retorna uma lista de saldos atualizados por setor.
    
    Parâmetros:
    - db: conexão SQLite aberta (passada da view Flask)
    - tipo: 'novo', 'entrada', 'saida', 'transferencia', 'ajuste'
    """
    from datetime import datetime

    if quantidade < 0 or peso < 0:
        raise ValueError("Quantidade e peso devem ser positivos")

    data = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor = db.cursor()
    saldos_atualizados = []

    # ===== FUNÇÃO AUXILIAR PARA ATUALIZAR ESTOQUE =====
    def atualizar_estoque(produto_id, setor, quantidade, peso):
        cursor.execute("""
            SELECT quantidade, peso FROM estoque
            WHERE produto_id = ? AND setor = ?
        """, (produto_id, setor))
        saldo = cursor.fetchone()

        if saldo:
            nova_quantidade = saldo["quantidade"] + quantidade
            novo_peso = saldo["peso"] + peso
            cursor.execute("""
                UPDATE estoque
                SET quantidade = ?, peso = ?, atualizado_em = ?
                WHERE produto_id = ? AND setor = ?
            """, (nova_quantidade, novo_peso, data, produto_id, setor))
        else:
            nova_quantidade = quantidade
            novo_peso = peso
            cursor.execute("""
                INSERT INTO estoque (produto_id, setor, quantidade, peso, atualizado_em)
                VALUES (?, ?, ?, ?, ?)
            """, (produto_id, setor, quantidade, peso, data))

        return {"setor": setor, "quantidade": nova_quantidade, "peso": novo_peso}

    # ===== REGISTRO DE MOVIMENTO =====
    try:
        if tipo == 'novo':
            cursor.execute("""
                INSERT INTO relatorio_novos_produtos (produto_id, setor, usuario_id, data)
                VALUES (?, ?, ?, ?)
            """, (produto_id, setor_destino, usuario_id, data))
            saldos_atualizados.append(atualizar_estoque(produto_id, setor_destino, quantidade, peso))

        elif tipo == 'entrada':
            cursor.execute("""
                INSERT INTO entradas (produto_id, setor, quantidade, peso, usuario_id, data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (produto_id, setor_destino, quantidade, peso, usuario_id, data))
            saldos_atualizados.append(atualizar_estoque(produto_id, setor_destino, quantidade, peso))

        elif tipo == 'saida':
            cursor.execute("""
                SELECT quantidade, peso FROM estoque
                WHERE produto_id = ? AND setor = ?
            """, (produto_id, setor_origem))
            saldo = cursor.fetchone()
            if not saldo or saldo["quantidade"] < quantidade or saldo["peso"] < peso:
                raise ValueError("Saldo insuficiente para saída")

            cursor.execute("""
                INSERT INTO saidas (produto_id, setor, quantidade, peso, usuario_id, data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (produto_id, setor_origem, quantidade, peso, usuario_id, data))
            saldos_atualizados.append(atualizar_estoque(produto_id, setor_origem, -quantidade, -peso))

        elif tipo == 'transferencia':
            cursor.execute("""
                SELECT quantidade, peso FROM estoque
                WHERE produto_id = ? AND setor = ?
            """, (produto_id, setor_origem))
            saldo = cursor.fetchone()
            if not saldo or saldo["quantidade"] < quantidade or saldo["peso"] < peso:
                raise ValueError("Saldo insuficiente para transferência")

            cursor.execute("""
                INSERT INTO transferencias (produto_id, de_setor, para_setor, quantidade, peso, usuario_id, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (produto_id, setor_origem, setor_destino, quantidade, peso, usuario_id, data))

            saldos_atualizados.append(atualizar_estoque(produto_id, setor_origem, -quantidade, -peso))
            saldos_atualizados.append(atualizar_estoque(produto_id, setor_destino, quantidade, peso))

        elif tipo == 'ajuste':
            cursor.execute("""
                INSERT INTO ajustes_saldo (produto_id, setor, quantidade, peso, usuario_id, data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (produto_id, setor_destino, quantidade, peso, usuario_id, data))
            saldos_atualizados.append(atualizar_estoque(produto_id, setor_destino, quantidade, peso))

        else:
            raise ValueError(f"Tipo de movimento inválido: {tipo}")

        # ===== REGISTRO NO LOG GERAL =====
        cursor.execute("""
            INSERT INTO movimentos (tipo, produto_id, de_setor, para_setor,
                                    quantidade, peso, usuario_id, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tipo, produto_id, setor_origem, setor_destino, quantidade, peso, usuario_id, data))

        db.commit()

    finally:
        cursor.close()  # garante fechamento do cursor

    return saldos_atualizados

 
# ================= DECORATOR LOGIN =================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Você precisa fazer login para acessar esta página.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ================= DECORATOR ADM =================
def adm_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('perfil') != 'ADM':
            flash("Acesso negado", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ================= RELATÓRIO: NOVOS PRODUTOS =================
def registrar_novo_produto_relatorio(cursor, produto):
    cursor.execute("""
        INSERT INTO relatorio_novos_produtos
        (produto_id, nome, setor, quantidade, peso, data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        produto.id,
        produto.nome,
        produto.setor,
        produto.quantidade,
        produto.peso,
        datetime.now()
    ))

# ================= ROTAS =================

# --- Login ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']

        conn = conectar()
        usuario = conn.execute(
            "SELECT * FROM usuarios WHERE email=?",
            (email,)
        ).fetchone()
        conn.close()

        if usuario and check_password_hash(usuario['senha'], senha):
            session['user_id'] = usuario['id']
            session['user_nome'] = usuario['nome']
            session['perfil'] = usuario['perfil']
            return redirect(url_for('dashboard'))
        else:
            flash("Usuário ou senha incorretos", "danger")

    return render_template("login.html")

# --- Recuperar Senha ---
@app.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    if request.method == "POST":
        email = request.form.get("email")
        flash(
            "Se o e-mail existir, enviaremos instruções para recuperação.",
            "info"
        )
        return redirect(url_for("login"))

    return render_template("recuperar_senha.html")

# --- Logout ---
@app.route('/logout')
def logout():
    session.clear()
    flash("Você saiu do sistema.", "success")
    return redirect(url_for('login'))

# --- Dashboard ---
@app.route('/dashboard')
@login_required
def dashboard():
    conn = conectar()
    cursor = conn.cursor()

    # Totais gerais
    cursor.execute("""
    SELECT 
        COALESCE(SUM(e.quantidade), 0) -
        COALESCE((
            SELECT SUM(s.quantidade) FROM saidas s
        ), 0) AS total_qtde
    FROM entradas e
    """)
    total_qtde = cursor.fetchone()["total_qtde"]

    cursor.execute("""
    SELECT 
        COALESCE(SUM(e.quantidade * p.peso_unitario), 0) -
        COALESCE((
            SELECT SUM(s.quantidade * p.peso_unitario)
            FROM saidas s
            JOIN produtos p ON p.id = s.produto_id
        ), 0) AS total_peso
    FROM entradas e
    JOIN produtos p ON p.id = e.produto_id
    """)
    total_peso = cursor.fetchone()["total_peso"]

    totais = {
    "total_qtde": total_qtde,
    "total_peso": total_peso
}

    # Todos os produtos
    produtos = cursor.execute("SELECT * FROM produtos").fetchall()

    # Entradas e saídas
    entradas = cursor.execute("""
        SELECT e.*, p.nome FROM entradas e
        JOIN produtos p ON p.id = e.produto_id
    """).fetchall()

    saidas = cursor.execute("""
        SELECT s.*, p.nome FROM saidas s
        JOIN produtos p ON p.id = s.produto_id
    """).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        totais=totais,
        produtos=produtos,
        entradas=entradas,
        saidas=saidas
    )

@app.route('/dashboard/dados')
@login_required
def dashboard_dados():
    conn = conectar()
    cursor = conn.cursor()

    entradas = cursor.execute("""
        SELECT e.*, p.nome FROM entradas e
        JOIN produtos p ON p.id = e.produto_id
    """).fetchall()

    saidas = cursor.execute("""
        SELECT s.*, p.nome FROM saidas s
        JOIN produtos p ON p.id = s.produto_id
    """).fetchall()

    conn.close()

    # Converter Row objects para dicts simples
    entradas_list = [{"nome": e["nome"], "quantidade": e["quantidade"]} for e in entradas]
    saidas_list = [{"nome": s["nome"], "quantidade": s["quantidade"]} for s in saidas]

    return {"entradas": entradas_list, "saidas": saidas_list}

# ================= ROTAS DE USUÁRIOS =================
@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@adm_required
def usuarios():
    conn = conectar()
    cursor = conn.cursor()

    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        cpf = request.form['cpf']
        senha = request.form['senha']
        perfil = request.form['perfil']

        try:
            cursor.execute("""
                INSERT INTO usuarios (nome, email, cpf, senha, perfil)
                VALUES (?, ?, ?, ?, ?)
            """, (
                nome,
                email,
                cpf,
                generate_password_hash(senha),
                perfil
            ))
            conn.commit()
            flash("Usuário cadastrado com sucesso!", "success")
        except sqlite3.IntegrityError:
            flash("Email ou CPF já cadastrado!", "danger")

    usuarios = cursor.execute("SELECT * FROM usuarios").fetchall()
    conn.close()
    return render_template("usuarios.html", usuarios=usuarios)

@app.route('/usuarios')
def listar_usuarios():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, usuario, nivel FROM usuarios")
    usuarios = cursor.fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=usuarios)


@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@login_required
@adm_required
def editar_usuario(id):
    conn = conectar()
    cursor = conn.cursor()

    # Pega os dados atuais do usuário
    cursor.execute("SELECT id, nome, email, cpf, perfil FROM usuarios WHERE id = ?", (id,))
    usuario = cursor.fetchone()

    if not usuario:
        flash("Usuário não encontrado.", "danger")
        conn.close()
        return redirect(url_for('usuarios'))

    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        cpf = request.form['cpf']
        perfil = request.form['perfil']

        # Atualiza no banco
        cursor.execute("""
            UPDATE usuarios
            SET nome = ?, email = ?, cpf = ?, perfil = ?
            WHERE id = ?
        """, (nome, email, cpf, perfil, id))
        conn.commit()
        conn.close()

        flash("Usuário atualizado com sucesso!", "success")
        return redirect(url_for('usuarios'))

    conn.close()
    return render_template('editar_usuario.html', usuario={
        'id': usuario['id'],
        'nome': usuario['nome'],
        'email': usuario['email'],
        'cpf': usuario['cpf'],
        'perfil': usuario['perfil']
    })

@app.route('/usuario/excluir/<int:usuario_id>')
@login_required
@adm_required
def excluir_usuario(usuario_id):
    conn = conectar()
    conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
    conn.commit()
    conn.close()
    flash("Usuário excluído com sucesso!", "success")
    return redirect(url_for('usuarios'))

# --- Cadastro de Produtos ---
@app.route('/novo_produto', methods=['GET', 'POST'])
@login_required
def novo_produto():
    if request.method == 'POST':
        nome = request.form.get('nome')
        codigo = request.form.get('codigo')
        descricao = request.form.get('descricao', '')
        tamanho = request.form.get('tamanho', '')
        peso_unitario = float(request.form.get('peso_unitario') or 0)
        setor = request.form.get('setor')
        quantidade = float(request.form.get('quantidade') or 0)
        usuario_id = session.get('user_id')

        # Calcula peso total automaticamente
        peso_total = round(quantidade * peso_unitario, 3)

        if not nome or not codigo or not setor:
            flash("Preencha todos os campos obrigatórios.", "warning")
            return redirect(url_for('novo_produto'))

        db = conectar()
        cursor = db.cursor()

        # 🔹 Verifica código duplicado
        existe = cursor.execute("SELECT 1 FROM produtos WHERE codigo = ?", (codigo,)).fetchone()
        if existe:
            flash("❌ Já existe um produto cadastrado com esse código.", "danger")
            return redirect(url_for('novo_produto'))

        # 🔹 Inserir produto
        cursor.execute("""
            INSERT INTO produtos (codigo, nome, descricao, tamanho, peso_unitario)
            VALUES (?, ?, ?, ?, ?)
        """, (codigo, nome, descricao, tamanho, peso_unitario))
        produto_id = cursor.lastrowid

        # 🔹 Registrar movimento "novo" e atualizar estoque
        registrar_movimento(
            db,
            tipo='novo',
            produto_id=produto_id,
            setor_destino=setor,
            quantidade=quantidade,
            peso=peso_total,  # envia peso total calculado
            usuario_id=usuario_id
        )

        db.commit()
        flash("✅ Produto cadastrado com sucesso!", "success")
        return redirect(url_for('relatorios'))

    return render_template('novo_produto.html')

# --- Entrada ---
@app.route('/entrada', methods=['GET', 'POST'])
@login_required
def entrada():
    db = conectar()
    cursor = db.cursor()

    if request.method == 'POST':
        produto_id = int(request.form['produto_id'])
        setor = request.form['setor']
        quantidade = float(request.form['quantidade'])
        peso = float(request.form['peso'])
        usuario_id = session.get('user_id')

        # 🔹 Registrar movimento de entrada
        registrar_movimento(
            db,
            tipo='entrada',
            produto_id=produto_id,
            setor_destino=setor,
            quantidade=quantidade,
            peso=peso,
            usuario_id=usuario_id
        )

        db.commit()
        flash('Entrada registrada com sucesso!', 'success')
        return redirect(url_for('entrada'))

    # 🔹 PRODUTOS ATIVOS + ESTOQUE TOTAL
    produtos = cursor.execute("""
        SELECT
            p.id,
            p.nome,
            p.codigo,
            p.peso_unitario,
            COALESCE(SUM(e.quantidade), 0) AS quantidade_estoque
        FROM produtos p
        LEFT JOIN estoque e ON e.produto_id = p.id
        WHERE p.ativo = 1
        GROUP BY p.id
        ORDER BY p.nome
    """).fetchall()

    return render_template('entrada.html', produtos=produtos)

# --- Saída ---
@app.route('/saida', methods=['GET', 'POST'])
@login_required
def saida():
    db = conectar()
    cursor = db.cursor()

    if request.method == 'POST':
        produto_id = int(request.form['produto_id'])
        setor = request.form['setor']
        quantidade = float(request.form['quantidade'])
        peso = float(request.form['peso'])
        usuario_id = session.get('user_id')

        # 🔹 Registrar movimento de saída
        try:
            registrar_movimento(
                db,
                tipo='saida',
                produto_id=produto_id,
                setor_origem=setor,
                quantidade=quantidade,
                peso=peso,
                usuario_id=usuario_id
            )
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('saida'))

        db.commit()
        flash('Saída registrada com sucesso!', 'success')
        return redirect(url_for('saida'))

    produtos = cursor.execute("""
        SELECT id, nome, peso_unitario
        FROM produtos
        WHERE ativo = 1
    """).fetchall()

    return render_template('saida.html', produtos=produtos)

# --- Transferir ---
@app.route('/transferir', methods=['GET', 'POST'])
@login_required
def transferir():
    db = conectar()
    cursor = db.cursor()
    usuario_id = session.get('user_id')

    if request.method == 'POST':
        produto_id = int(request.form['produto_id'])
        de_setor = request.form['de_setor']
        para_setor = request.form['para_setor']
        quantidade = float(request.form['quantidade'])
        peso = float(request.form['peso'])

        if de_setor == para_setor:
            flash('O setor de origem e destino não podem ser iguais.', 'warning')
            return redirect(url_for('transferir'))

        if quantidade <= 0 or peso < 0:
            flash('Quantidade ou peso inválido.', 'danger')
            return redirect(url_for('transferir'))

        # 🔹 Garantir estoque nos dois setores
        cursor.execute("""
            INSERT OR IGNORE INTO estoque (produto_id, setor, quantidade, peso)
            VALUES (?, ?, 0, 0)
        """, (produto_id, de_setor))
        cursor.execute("""
            INSERT OR IGNORE INTO estoque (produto_id, setor, quantidade, peso)
            VALUES (?, ?, 0, 0)
        """, (produto_id, para_setor))

        # 🔹 Buscar saldo do setor de origem
        cursor.execute("""
            SELECT quantidade, peso
            FROM estoque
            WHERE produto_id = ? AND setor = ?
        """, (produto_id, de_setor))
        saldo = cursor.fetchone()

        if not saldo or saldo['quantidade'] < quantidade:
            disponivel = saldo['quantidade'] if saldo else 0
            flash(f"Saldo insuficiente! Disponível: {disponivel}", 'danger')
            return redirect(url_for('transferir'))

        # 🔹 Atualizar estoque
        cursor.execute("""
            UPDATE estoque
            SET quantidade = quantidade - ?, peso = peso - ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE produto_id = ? AND setor = ?
        """, (quantidade, peso, produto_id, de_setor))

        cursor.execute("""
            UPDATE estoque
            SET quantidade = quantidade + ?, peso = peso + ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE produto_id = ? AND setor = ?
        """, (quantidade, peso, produto_id, para_setor))

        # 🔹 Registrar movimentação
        registrar_movimento(
            db=db,
            tipo='transferencia',
            produto_id=produto_id,
            setor_origem=de_setor,
            setor_destino=para_setor,
            quantidade=quantidade,
            peso=peso,
            usuario_id=usuario_id
        )

        db.commit()
        flash('Transferência realizada com sucesso!', 'success')
        return redirect(url_for('transferir'))

    # 🔹 GET — produtos ativos
    produtos = [dict(row) for row in cursor.execute("""
        SELECT id, nome, peso_unitario
        FROM produtos
        WHERE ativo = 1
        ORDER BY nome
    """).fetchall()]

    # 🔹 GET — estoque enriquecido com nome e peso_unitario
    estoque = [dict(row) for row in cursor.execute("""
        SELECT
            e.produto_id,
            e.setor,
            e.quantidade,
            e.peso,
            p.nome AS produto_nome,
            p.peso_unitario
        FROM estoque e
        JOIN produtos p ON p.id = e.produto_id
    """).fetchall()]

    db.close()

    return render_template(
        'transferir.html',
        produtos=produtos,
        estoque=estoque
    )

# --- Relatórios ---
@app.route('/relatorios')
@login_required
def relatorios():
    db = conectar()
    cursor = db.cursor()

    # 🔹 NOVOS PRODUTOS (baseado no movimento "novo")
    novos_produtos = cursor.execute("""
        SELECT
            m.id,
            p.codigo,
            p.nome,
            COALESCE(u.nome, 'Não informado') AS usuario_nome,
            m.data
        FROM movimentos m
        JOIN produtos p ON p.id = m.produto_id
        LEFT JOIN usuarios u ON u.id = m.usuario_id
        WHERE m.tipo = 'novo'
        ORDER BY m.data DESC
    """).fetchall()

    # 🔹 ENTRADAS
    entradas = cursor.execute("""
        SELECT
            e.id,
            p.nome,
            e.quantidade,
            e.peso,
            COALESCE(u.nome, 'Não informado') AS usuario_nome,
            e.data
        FROM entradas e
        LEFT JOIN produtos p ON e.produto_id = p.id
        LEFT JOIN usuarios u ON e.usuario_id = u.id
        ORDER BY e.data DESC
    """).fetchall()

    # 🔹 SAÍDAS
    saidas = cursor.execute("""
        SELECT
            s.id,
            p.nome,
            s.quantidade,
            s.peso,
            COALESCE(u.nome, 'Não informado') AS usuario_nome,
            s.data
        FROM saidas s
        LEFT JOIN produtos p ON s.produto_id = p.id
        LEFT JOIN usuarios u ON s.usuario_id = u.id
        ORDER BY s.data DESC
    """).fetchall()

    # 🔹 TRANSFERÊNCIAS
    transferencias = cursor.execute("""
        SELECT
            t.id,
            p.nome,
            t.de_setor,
            t.para_setor,
            t.quantidade,
            t.peso,
            COALESCE(u.nome, 'Não informado') AS usuario_nome,
            t.data
        FROM transferencias t
        LEFT JOIN produtos p ON t.produto_id = p.id
        LEFT JOIN usuarios u ON t.usuario_id = u.id
        ORDER BY t.data DESC
    """).fetchall()

    # 🔹 AJUSTES DE SALDO
    ajustes = cursor.execute("""
        SELECT
            a.id,
            p.nome,
            a.quantidade,
            a.peso,
            COALESCE(u.nome, 'Não informado') AS usuario_nome,
            a.data
        FROM ajustes_saldo a
        LEFT JOIN produtos p ON a.produto_id = p.id
        LEFT JOIN usuarios u ON a.usuario_id = u.id
        ORDER BY a.data DESC
    """).fetchall()

    # 🔹 TOTAIS GERAIS
    totais = cursor.execute("""
        SELECT
            COALESCE(SUM(quantidade), 0) AS total_qtde,
            COALESCE(SUM(peso), 0) AS total_peso
        FROM estoque
    """).fetchone()

    db.close()

    return render_template(
        'relatorios.html',
        novos_produtos=novos_produtos,
        entradas=entradas,
        saidas=saidas,
        transferencias=transferencias,
        ajustes=ajustes,
        totais=totais
    )

# --- Ajustar Saldo (ADM) ---
@app.route('/ajustar_saldo', methods=['GET', 'POST'])
@login_required
@adm_required
def ajustar_saldo():
    db = conectar()
    cursor = db.cursor()

    if request.method == 'POST':
        produto_id = int(request.form.get('produto_id'))
        setor = request.form.get('setor')
        quantidade = float(request.form.get('quantidade'))
        peso = float(request.form.get('peso'))
        usuario_id = session.get('user_id')

        # 🔹 Registrar movimento de ajuste
        registrar_movimento(
            db,
            tipo='ajuste',
            produto_id=produto_id,
            setor_destino=setor,
            quantidade=quantidade,
            peso=peso,
            usuario_id=usuario_id
        )

        db.commit()
        flash("Saldo ajustado com sucesso!", "success")

    produtos = cursor.execute("""
        SELECT
            e.id AS estoque_id,
            p.id AS produto_id,
            p.nome,
            e.setor,
            e.quantidade,
            e.peso
        FROM estoque e
        JOIN produtos p ON p.id = e.produto_id
        WHERE p.ativo = 1
        ORDER BY p.nome, e.setor
    """).fetchall()

    return render_template("ajustar_saldo.html", produtos=produtos)

# --- Excluir Produto (Exclusão Lógica) ---
@app.route("/excluir_produto", methods=["POST"])
@login_required
@adm_required
def excluir_produto():
    produto_id = int(request.form["produto_id"])

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE produtos
        SET ativo = 0
        WHERE id = ?
    """, (produto_id,))

    conn.commit()
    conn.close()

    flash("Produto desativado com sucesso!", "success")
    return redirect(url_for("ajustar_saldo"))

# ================= ROTA: Redefinir Senha pelo Usuário =================
@app.route('/redefinir_senha_usuario', methods=['GET', 'POST'])
def redefinir_senha_usuario():
    if request.method == 'POST':
        usuario_input = request.form.get('usuario', '').strip()
        nova_senha = request.form.get('nova_senha', '').strip()

        if not usuario_input or not nova_senha:
            flash("Preencha todos os campos.", "warning")
            return redirect(url_for('redefinir_senha_usuario'))

        conn = conectar()
        cursor = conn.cursor()

        try:
            # 🔹 Busca usuário pelo nome
            cursor.execute(
                "SELECT id FROM usuarios WHERE nome = ?",
                (usuario_input,)
            )
            usuario = cursor.fetchone()

            if not usuario:
                flash("Usuário não encontrado.", "danger")
                return redirect(url_for('redefinir_senha_usuario'))

            # 🔹 Atualiza senha com hash
            senha_hash = generate_password_hash(nova_senha)

            cursor.execute("""
                UPDATE usuarios
                SET senha = ?
                WHERE id = ?
            """, (senha_hash, usuario['id']))

            conn.commit()
            flash("Senha redefinida com sucesso!", "success")
            return redirect(url_for('login'))

        except Exception as e:
            conn.rollback()
            flash("Erro ao redefinir a senha.", "danger")
            return redirect(url_for('redefinir_senha_usuario'))

        finally:
            conn.close()

    # 🔹 GET
    return render_template("redefinir_senha_usuario.html")
#################################
from flask import jsonify, request

@app.route('/estoque/saldo')
@login_required
def estoque_saldo():
    produto_id = request.args.get('produto_id', type=int)
    setor = request.args.get('setor', type=str)

    if not produto_id or not setor:
        return jsonify({'quantidade': 0})

    db = conectar()  # sua função de conexão com o banco
    cursor = db.cursor()

    # Consulta a quantidade disponível no estoque
    cursor.execute("""
        SELECT SUM(quantidade) as total
        FROM estoque
        WHERE produto_id = ? AND setor = ?
    """, (produto_id, setor))

    resultado = cursor.fetchone()
    quantidade_disponivel = resultado['total'] if resultado['total'] is not None else 0

    return jsonify({'quantidade': quantidade_disponivel})

# ================= INICIALIZAÇÃO =================
if __name__ == '__main__':
    criar_banco()
    # app.run(debug=True)  # REMOVIDO para produção no Railway

