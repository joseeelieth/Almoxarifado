import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

DATABASE = "banco.db"


# ================= CONEXÃO =================
def conectar():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ================= CRIAR TABELAS =================
def criar_tabelas():
    conn = conectar()
    cursor = conn.cursor()

    # ---------- USUÁRIOS ----------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        cpf TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK(perfil IN ('ADMIN', 'OPERADOR')),
        ativo INTEGER DEFAULT 1,
        criado_em TEXT
    )
    """)

    # ---------- PRODUTOS ----------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        setor TEXT NOT NULL,
        quantidade REAL DEFAULT 0,
        peso REAL DEFAULT 0,
        criado_em TEXT
    )
    """)

    # ---------- MOVIMENTAÇÕES ----------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimentacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        tipo TEXT CHECK(tipo IN ('ENTRADA', 'SAIDA', 'TRANSFERENCIA', 'AJUSTE')),
        quantidade REAL,
        peso REAL,
        setor_origem TEXT,
        setor_destino TEXT,
        usuario_id INTEGER,
        data TEXT,
        FOREIGN KEY(produto_id) REFERENCES produtos(id),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )
    """)

    conn.commit()
    conn.close()


# ================= USUÁRIOS =================
def criar_usuario(nome, email, cpf, senha, perfil):
    conn = conectar()
    cursor = conn.cursor()
    senha_hash = generate_password_hash(senha)

    cursor.execute("""
    INSERT INTO usuarios (nome, email, cpf, senha, perfil, criado_em)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (nome, email, cpf, senha_hash, perfil, datetime.now()))

    conn.commit()
    conn.close()


def autenticar_usuario(email, senha):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM usuarios WHERE email = ? AND ativo = 1", (email,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user["senha"], senha):
        return user
    return None


def listar_usuarios():
    conn = conectar()
    usuarios = conn.execute("SELECT * FROM usuarios").fetchall()
    conn.close()
    return usuarios


# ================= PRODUTOS =================
def criar_produto(nome, setor):
    conn = conectar()
    conn.execute("""
    INSERT INTO produtos (nome, setor, criado_em)
    VALUES (?, ?, ?)
    """, (nome, setor, datetime.now()))
    conn.commit()
    conn.close()


def listar_produtos():
    conn = conectar()
    produtos = conn.execute("SELECT * FROM produtos").fetchall()
    conn.close()
    return produtos


def obter_produto(produto_id):
    conn = conectar()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    conn.close()
    return produto


# ================= MOVIMENTAÇÕES =================
def registrar_entrada(produto_id, quantidade, peso, usuario_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE produtos
    SET quantidade = quantidade + ?, peso = peso + ?
    WHERE id = ?
    """, (quantidade, peso, produto_id))

    cursor.execute("""
    INSERT INTO movimentacoes
    (produto_id, tipo, quantidade, peso, usuario_id, data)
    VALUES (?, 'ENTRADA', ?, ?, ?, ?)
    """, (produto_id, quantidade, peso, usuario_id, datetime.now()))

    conn.commit()
    conn.close()


def registrar_saida(produto_id, quantidade, peso, usuario_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE produtos
    SET quantidade = quantidade - ?, peso = peso - ?
    WHERE id = ?
    """, (quantidade, peso, produto_id))

    cursor.execute("""
    INSERT INTO movimentacoes
    (produto_id, tipo, quantidade, peso, usuario_id, data)
    VALUES (?, 'SAIDA', ?, ?, ?, ?)
    """, (produto_id, quantidade, peso, usuario_id, datetime.now()))

    conn.commit()
    conn.close()


def transferir_produto(produto_id, setor_destino, quantidade, peso, usuario_id):
    conn = conectar()
    cursor = conn.cursor()

    produto = obter_produto(produto_id)

    cursor.execute("""
    UPDATE produtos
    SET setor = ?
    WHERE id = ?
    """, (setor_destino, produto_id))

    cursor.execute("""
    INSERT INTO movimentacoes
    (produto_id, tipo, quantidade, peso, setor_origem, setor_destino, usuario_id, data)
    VALUES (?, 'TRANSFERENCIA', ?, ?, ?, ?, ?, ?)
    """, (
        produto_id,
        quantidade,
        peso,
        produto["setor"],
        setor_destino,
        usuario_id,
        datetime.now()
    ))

    conn.commit()
    conn.close()


def ajustar_saldo(produto_id, quantidade, peso, usuario_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE produtos
    SET quantidade = ?, peso = ?
    WHERE id = ?
    """, (quantidade, peso, produto_id))

    cursor.execute("""
    INSERT INTO movimentacoes
    (produto_id, tipo, quantidade, peso, usuario_id, data)
    VALUES (?, 'AJUSTE', ?, ?, ?, ?)
    """, (produto_id, quantidade, peso, usuario_id, datetime.now()))

    conn.commit()
    conn.close()


# ================= RELATÓRIOS =================
def listar_movimentacoes():
    conn = conectar()
    dados = conn.execute("""
    SELECT m.*, p.nome AS produto, u.nome AS usuario
    FROM movimentacoes m
    JOIN produtos p ON m.produto_id = p.id
    JOIN usuarios u ON m.usuario_id = u.id
    ORDER BY m.data DESC
    """).fetchall()
    conn.close()
    return dados
