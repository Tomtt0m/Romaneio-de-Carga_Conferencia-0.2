from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import io
from fpdf import FPDF
from io import BytesIO
import zipfile
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = 'senha_super_secreta'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///romaneio.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Modelos ---

class Transportadora(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cnpj = db.Column(db.String(20), unique=True, nullable=False)
    senha_hash = db.Column(db.String(128), nullable=False)
    transportadora_id = db.Column(db.Integer, db.ForeignKey('transportadora.id'), nullable=False)
    transportadora = db.relationship('Transportadora')

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)
    def checa_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

class Romaneio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pre_nota = db.Column(db.String(50), nullable=False)
    num_nota = db.Column(db.String(50), nullable=False)
    data_emissao = db.Column(db.Date, nullable=False)  # <-- Alterado para Date
    status = db.Column(db.String(20), default='pendente')
    transportadora_id = db.Column(db.Integer, db.ForeignKey('transportadora.id'), nullable=False)
    transportadora = db.relationship('Transportadora')

class Volume(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_caixa = db.Column(db.String(100))
    matricula = db.Column(db.String(50))
    quantidade = db.Column(db.Integer)
    palete = db.Column(db.String(50))
    status = db.Column(db.String(50), default='pendente')
    codigo = db.Column(db.String(50))
    
    cod_regiao = db.Column(db.String(10))
    regiao = db.Column(db.String(100))
    cliente = db.Column(db.String(200))
    produto = db.Column(db.String(200))
    rota = db.Column(db.String(50))
    pre_nota = db.Column(db.String(50))
    numero_caixa = db.Column(db.String(50))
    chave_de_acesso = db.Column(db.String(200))

    romaneio_id = db.Column(db.Integer, db.ForeignKey('romaneio.id'))
    romaneio = db.relationship('Romaneio', backref=db.backref('volumes', lazy=True))

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200))
    cliente = db.Column(db.String(200))   # ← Adicionado
    destino = db.Column(db.String(200))   # ← Adicionado
    regiao = db.Column(db.String(20))     # ← Adicionado
    volume_id = db.Column(db.Integer, db.ForeignKey('volume.id'))
    volume = db.relationship('Volume', backref=db.backref('itens', lazy=True))

# --- Rotas ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cnpj = request.form['cnpj']
        senha = request.form['senha']
        user = Usuario.query.filter_by(cnpj=cnpj).first()
        if user and user.checa_senha(senha):
            session['user_id'] = user.id
            session['transportadora_id'] = user.transportadora_id
            return redirect(url_for('menu'))
        else:
            return render_template('login.html', erro='CNPJ ou senha incorretos')
    return render_template('login.html')

from datetime import datetime

@app.route('/menu')
def menu():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    transportadora_id = session['transportadora_id']

    pre_nota_filter = request.args.get('pre_nota')
    status_filter = request.args.get('status')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    # Query base filtrando pela transportadora
    romaneios = Romaneio.query.filter_by(transportadora_id=transportadora_id)

    if pre_nota_filter:
        romaneios = romaneios.filter(Romaneio.pre_nota.like(f'%{pre_nota_filter}%'))

    if status_filter:
        romaneios = romaneios.filter_by(status=status_filter)

    # Filtrar por data de emissão entre data_inicio e data_fim, convertendo string para date
    # Assumindo que data_emissao está no formato 'YYYY-MM-DD'
    def str_to_date(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except:
            return None

    di = str_to_date(data_inicio) if data_inicio else None
    df = str_to_date(data_fim) if data_fim else None

    # Para usar filtros com SQLAlchemy, converta a coluna para Date:
    from sqlalchemy import cast, Date

    if di:
        romaneios = romaneios.filter(cast(Romaneio.data_emissao, Date) >= di)
    if df:
        romaneios = romaneios.filter(cast(Romaneio.data_emissao, Date) <= df)

    romaneios = romaneios.all()

    # calcula progresso por romaneio
    progresso = {}
    for r in romaneios:
        total = len(r.volumes)
        confirmados = sum(1 for v in r.volumes if v.status == 'confirmado')
        progresso[r.id] = int(confirmados / total * 100) if total > 0 else 0

    return render_template('menu.html', romaneios=romaneios, progresso=progresso)


@app.route('/romaneio/<int:id>')
def romaneio(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    rom = Romaneio.query.get_or_404(id)
    if rom.transportadora_id != session['transportadora_id']:
        return "Acesso negado", 403
    return render_template('romaneio.html', romaneio=rom)

@app.route('/api/volumes/<int:romaneio_id>')
def api_volumes(romaneio_id):
    volumes = Volume.query.filter_by(romaneio_id=romaneio_id).all()
    lista = []
    for v in volumes:
        lista.append({
            'id': v.id,
            'tipo_caixa': v.tipo_caixa,
            'matricula': v.matricula,
            'quantidade': v.quantidade,
            'status': v.status
        })
    return jsonify(lista)

@app.route('/api/itens/<int:volume_id>')
def api_itens(volume_id):
    itens = Item.query.filter_by(volume_id=volume_id).all()
    lista = [{'descricao': i.descricao} for i in itens]
    return jsonify(lista)

@app.route('/api/confirmar_volume', methods=['POST'])
def confirmar_volume():
    data = request.json
    vol_id = data.get('volume_id')
    status = data.get('status')  # 'confirmado' ou 'faltante'
    volume = Volume.query.get(vol_id)
    if volume and volume.romaneio.transportadora_id == session['transportadora_id']:
        volume.status = status
        db.session.commit()
        return jsonify({'sucesso': True})
    return jsonify({'sucesso': False}), 403

@app.route('/api/progresso/<int:romaneio_id>')
def api_progresso(romaneio_id):
    volumes = Volume.query.filter_by(romaneio_id=romaneio_id).all()
    total = len(volumes)
    confirmados = sum(1 for v in volumes if v.status == 'confirmado')
    return jsonify({'total': total, 'confirmados': confirmados})

@app.route('/validar_volume', methods=['POST'])
def validar_volume():
    if 'user_id' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401

    dados = request.get_json()
    qr_code = dados.get('chave') or dados.get('qr_code')  # aceita 'chave' ou 'qr_code' conforme o front

    if not qr_code:
        return jsonify({'erro': 'QR code inválido'}), 400

    pre_nota = None
    if len(qr_code) >= 18:
        pre_nota = qr_code[11:18]  # Ajuste conforme estrutura real do QR

    # Busca primeiro pelo chave_de_acesso
    volume = Volume.query.join(Romaneio).filter(
        Volume.chave_de_acesso == qr_code,
        Volume.status != 'confirmado',
        Romaneio.transportadora_id == session['transportadora_id']
    ).first()

    # Se não encontrar, busca pelo pre_nota
    if not volume and pre_nota:
        volume = Volume.query.join(Romaneio).filter(
            Romaneio.pre_nota == pre_nota,
            Volume.status != 'confirmado',
            Romaneio.transportadora_id == session['transportadora_id']
        ).first()

    if not volume:
        return jsonify({'erro': 'Volume não encontrado ou já conferido'}), 404

    volume.status = 'confirmado'
    db.session.commit()

    return jsonify({
        'mensagem': 'Volume conferido com sucesso',
        'volume_id': volume.id,
        'tipo_caixa': volume.tipo_caixa,
        'matricula': volume.matricula
    })


@app.route('/progresso/<int:romaneio_id>')
def progresso_conferencia(romaneio_id):
    romaneio = Romaneio.query.get_or_404(romaneio_id)
    if romaneio.transportadora_id != session['transportadora_id']:
        return jsonify({'erro': 'Acesso negado'}), 403

    total = len(romaneio.volumes)
    conferidos = sum(1 for v in romaneio.volumes if v.status == 'confirmado')

    return jsonify({
        'total': total,
        'conferidos': conferidos,
        'porcentagem': round((conferidos / total) * 100, 2) if total else 0
    })

@app.route('/finalizar_conferencia', methods=['POST'])
def finalizar_conferencia():
    if 'user_id' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401

    dados = request.get_json()
    romaneio_id = dados.get('romaneio_id')
    if not romaneio_id:
        return jsonify({'erro': 'ID do romaneio é obrigatório'}), 400

    romaneio = Romaneio.query.get(romaneio_id)
    if not romaneio:
        return jsonify({'erro': 'Romaneio não encontrado'}), 404

    if romaneio.transportadora_id != session['transportadora_id']:
        return jsonify({'erro': 'Acesso negado'}), 403

    volumes = romaneio.volumes
    total = len(volumes)
    conferidos = sum(1 for v in volumes if v.status == 'confirmado')

    # Define status do romaneio
    if total > 0 and conferidos == total:
        romaneio.status = 'finalizado'
    else:
        romaneio.status = 'pendente'

    db.session.commit()

    return jsonify({
        'total': total,
        'conferidos': conferidos,
        'status_romaneio': romaneio.status
    })


@app.route('/faltantes/<int:romaneio_id>')
def volumes_faltantes(romaneio_id):
    romaneio = Romaneio.query.get_or_404(romaneio_id)
    if romaneio.transportadora_id != session['transportadora_id']:
        return jsonify({'erro': 'Acesso negado'}), 403

    volumes = [v for v in romaneio.volumes if v.status != 'confirmado']
    resultado = [{
        'id': v.id,
        'tipo_caixa': v.tipo_caixa,
        'matricula': v.matricula
    } for v in volumes]

    return jsonify({'faltantes': resultado})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Inicialização banco (execução única) ---

def criar_dados_iniciais():
    with app.app_context():
        db.create_all()
        if not Transportadora.query.first():
            t1 = Transportadora(nome='Transportadora A')
            db.session.add(t1)

            u1 = Usuario(cnpj='12345678000199', transportadora=t1)
            u1.set_senha('1234')
            db.session.add(u1)

            datas = [
                datetime.strptime("28-07-2025", "%d-%m-%Y").date(),
                datetime.strptime("29-07-2025", "%d-%m-%Y").date(),
                datetime.strptime("30-07-2025", "%d-%m-%Y").date()
            ]

            romaneios = []

            for i, data in enumerate(datas):
                r = Romaneio(pre_nota=f'PN100{i+1}', num_nota=f'NF100{i+1}', data_emissao=data, transportadora=t1)
                db.session.add(r)
                romaneios.append(r)

            volumes = [
                # Romaneio 1
                Volume(
                    tipo_caixa='Caixa Mista',
                    matricula='MTR001',
                    quantidade=10,
                    codigo='549350',
                    palete='0067',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='707 AUTO – SERVIÇO DE ALIMENTOS',
                    produto='CO PANTENE 510ML BIOTINAMINA B3',
                    rota='0864',
                    pre_nota='549350',
                    numero_caixa='0067',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[0]
                    
                ),
                Volume(
                    tipo_caixa='Caixa Indústria',
                    matricula='MTR002',
                    quantidade=5,
                    codigo='111222',
                    palete='0068',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='SUPERMERCADO IDEAL',
                    produto='SH HEAD & SHOULDERS MENTA 400ML',
                    rota='0864',
                    pre_nota='549351',
                    numero_caixa='0068',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[0]
                    
                ),

                # Romaneio 2
                Volume(
                    tipo_caixa='Caixa Padrão',
                    matricula='MTR003',
                    quantidade=8,
                    codigo='333444',
                    palete='0070',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='MERCADO CENTRAL',
                    produto='CREME DENTAL COLGATE TRIPLA 90G',
                    rota='0864',
                    pre_nota='549352',
                    numero_caixa='0070',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[1]
                    
                ),
                Volume(
                    tipo_caixa='Caixa Especial',
                    matricula='MTR004',
                    quantidade=12,
                    codigo='888999',
                    palete='0071',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='ATACADÃO ALVORADA',
                    produto='OMO LÍQUIDO 3L',
                    rota='0864',
                    pre_nota='549353',
                    numero_caixa='0071',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[1]
                    
                ),

                # Romaneio 3
                Volume(
                    tipo_caixa='Caixa Mista',
                    matricula='MTR005',
                    quantidade=7,
                    codigo='777666',
                    palete='0072',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='DROGASIL SA',
                    produto='FRALDA HUGGIES TRIPLA PROTEÇÃO G',
                    rota='0864',
                    pre_nota='549354',
                    numero_caixa='0072',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[2]
                    
                ),
                Volume(
                    tipo_caixa='Caixa Padrão',
                    matricula='MTR006',
                    quantidade=6,
                    codigo='123123',
                    palete='0073',
                    cod_regiao='18',
                    regiao='E DIRETA',
                    cliente='SUPERMERCADO IDEAL',
                    produto='BISCOITO NESFIT CACAU 170G',
                    rota='0864',
                    pre_nota='549355',
                    numero_caixa='0073',
                    chave_de_acesso="670103050086405493500000001820250729006769",
                    romaneio=romaneios[2]
                    
                ),
            ]
            db.session.add_all(volumes)

            itens = [
                # Volume 1
                Item(
                    descricao='CO PANTENE 510ML BIOTINAMINA B3',
                    cliente='707 AUTO – SERVIÇO DE ALIMENTOS',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[0]
                ),
                Item(
                    descricao='SH HEAD & SHOULDERS MENTA 400ML',
                    cliente='707 AUTO – SERVIÇO DE ALIMENTOS',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[0]
                ),

                # Volume 2
                Item(
                    descricao='DESODORANTE AER NIVEA MEN 150ML',
                    cliente='SUPERMERCADO IDEAL',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[1]
                ),

                # Volume 3
                Item(
                    descricao='CREME DENTAL COLGATE TRIPLA 90G',
                    cliente='MERCADO CENTRAL',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[2]
                ),
                Item(
                    descricao='SABONETE LUX MACIEZ FLORAL 85G',
                    cliente='MERCADO CENTRAL',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[2]
                ),

                # Volume 4
                Item(
                    descricao='AMACIANTE COMFORT 1L',
                    cliente='ATACADÃO ALVORADA',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[3]
                ),
                Item(
                    descricao='OMO LÍQUIDO 3L',
                    cliente='ATACADÃO ALVORADA',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[3]
                ),

                # Volume 5
                Item(
                    descricao='FRALDA HUGGIES TRIPLA PROTEÇÃO G',
                    cliente='DROGASIL SA',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[4]
                ),

                # Volume 6
                Item(
                    descricao='BISCOITO NESFIT CACAU 170G',
                    cliente='SUPERMERCADO IDEAL',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[5]
                ),
                Item(
                    descricao='LEITE EM PÓ NINHO INSTANTÂNEO 400G',
                    cliente='SUPERMERCADO IDEAL',
                    destino='E DIRETA',
                    regiao='18',
                    volume=volumes[5]
                ),
            ]
            db.session.add_all(itens)

            db.session.commit()



@app.route('/pdf/<int:romaneio_id>')
def gerar_pdf(romaneio_id):
    rom = Romaneio.query.get_or_404(romaneio_id)
    if rom.transportadora_id != session['transportadora_id']:
        return "Acesso negado", 403
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Romaneio Pré-Nota: {rom.pre_nota}", ln=True)
    pdf.cell(200, 10, txt=f"Nota Fiscal: {rom.num_nota}", ln=True)
    pdf.cell(200, 10, txt=f"Data de Emissão: {rom.data_emissao}", ln=True)
    pdf.cell(200, 10, txt="Volumes:", ln=True)
    for v in rom.volumes:
        pdf.cell(200, 10, txt=f" - {v.tipo_caixa} ({v.matricula}) - Quantidade: {v.quantidade} - Status: {v.status}", ln=True)
    
    pdf_bytes = pdf.output(dest='S').encode('latin1')  # gera PDF em bytes
    pdf_buffer = BytesIO(pdf_bytes)
    
    return send_file(pdf_buffer,
                     download_name=f'romaneio_{rom.pre_nota}.pdf',
                     as_attachment=True,
                     mimetype='application/pdf')

@app.route('/gerar_pdf_lote')
def gerar_pdf_lote():
    ids = request.args.getlist('ids')

    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        for romaneio_id in ids:
            romaneio = Romaneio.query.get(romaneio_id)
            if not romaneio:
                continue

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)

            # Cabeçalho
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(200, 10, txt=f"Romaneio: {romaneio.pre_nota}", ln=True)
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt=f"Nota Fiscal: {romaneio.num_nota}", ln=True)
            pdf.cell(200, 10, txt=f"Data de Emissão: {romaneio.data_emissao}", ln=True)
            pdf.cell(200, 10, txt=f"Status Geral: {romaneio.status}", ln=True)
            pdf.ln(10)

            # Tabela de volumes
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(50, 10, "Tipo de Caixa", 1)
            pdf.cell(50, 10, "Matrícula", 1)
            pdf.cell(40, 10, "Quantidade", 1)
            pdf.cell(40, 10, "Status", 1)
            pdf.ln()

            pdf.set_font("Arial", size=11)
            for v in romaneio.volumes:
                pdf.cell(50, 10, v.tipo_caixa, 1)
                pdf.cell(50, 10, v.matricula, 1)
                pdf.cell(40, 10, str(v.quantidade), 1)
                pdf.cell(40, 10, v.status, 1)
                pdf.ln()

            # Salvar PDF na memória
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            nome_pdf = f"romaneio_{romaneio.pre_nota or romaneio.id}.pdf"
            zip_file.writestr(nome_pdf, pdf_bytes)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='romaneios_completos.zip'
    )


if __name__ == '__main__':
    if not os.path.exists('romaneio.db'):
        criar_dados_iniciais()
    app.run(debug=True, host='0.0.0.0')
