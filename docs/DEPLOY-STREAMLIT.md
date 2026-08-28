# Deploy — Streamlit Community Cloud

## Credenciais de autenticação

`auth/users.yaml` está no `.gitignore` e **nunca vai ao repositório**.

O app detecta o ambiente automaticamente:

- **Local**: lê `auth/users.yaml` em disco.
- **Nuvem**: lê `st.secrets["auth"]` configurado no painel do Streamlit Cloud.

---

## Configurar secrets no painel

Em **App settings → Secrets**, cole o bloco abaixo substituindo os placeholders:

```toml
[auth]

[auth.cookie]
name = "dcubic_auth"
key  = "TROQUE_POR_UMA_STRING_ALEATORIA_LONGA"
expiry_days = 0.020833   # 30 minutos

[auth.credentials]

[auth.credentials.usernames]

[auth.credentials.usernames."abedrdador@gmail.com"]
email              = "abedrdador@gmail.com"
name               = "Dr. Abe"
password           = "HASH_BCRYPT_DA_SENHA_DO_DR_ABE"
role               = "Administrador"
active             = true
must_change_password = false
protected          = true

[auth.credentials.usernames."mary@usp.br"]
email              = "mary@usp.br"
name               = "Mary Caroline Skelton Macedo"
password           = "HASH_BCRYPT_DA_SENHA_DA_MARY"
role               = "Pesquisador"
active             = true
must_change_password = true
protected          = false
```

### Gerar hash bcrypt de uma senha

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw('SENHA_AQUI'.encode(), bcrypt.gensalt()).decode())"
```

---

## Caminho A (leitura local de pasta STL)

Na nuvem o diretório `~/Desktop/DCUBIC-SITE/MICROTOMO` não existe.
O app detecta isso e oculta o campo de pasta, exibindo um aviso.
Upload de arquivos STL continua disponível normalmente.

---

## packages.txt

Dependências de sistema necessárias para PyVista/VTK no Linux da nuvem:

```
libgl1
libglu1-mesa
xvfb
```

---

## Checklist pré-deploy

- [ ] Hash bcrypt atualizado nos Secrets do painel (não no repositório)
- [ ] `auth/users.yaml` confirmado fora do Git (`git check-ignore auth/users.yaml`)
- [ ] `packages.txt` presente na raiz do repositório
- [ ] `kaleido` em `requirements.txt`
- [ ] Testar login com a senha definitiva antes de divulgar o link
