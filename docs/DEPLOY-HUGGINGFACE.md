# Deploy — Hugging Face Spaces

## Autenticação via variável de ambiente

O Hugging Face Spaces não suporta seções TOML aninhadas como o Streamlit Cloud.
A autenticação é feita via uma única variável de ambiente: **`AUTH_CONFIG_JSON`**.

### Como configurar

No painel do Space: **Settings → Repository secrets → New secret**

- **Nome:** `AUTH_CONFIG_JSON`
- **Valor:** o JSON de uma linha abaixo (com os hashes reais no lugar dos placeholders)

```json
{"cookie":{"name":"dcubic_auth","key":"COOKIE_KEY_AQUI","expiry_days":1},"credentials":{"usernames":{"abedrdador@gmail.com":{"email":"abedrdador@gmail.com","name":"Dr. Abe","password":"HASH_BCRYPT_DR_ABE","role":"Administrador","active":true,"must_change_password":false,"protected":true},"mary@usp.br":{"email":"mary@usp.br","name":"Mary Caroline Skelton Macedo","password":"HASH_BCRYPT_MARY","role":"Pesquisador","active":true,"must_change_password":true,"protected":false}}}}
```

> **Atenção:** substitua `COOKIE_KEY_AQUI`, `HASH_BCRYPT_DR_ABE` e `HASH_BCRYPT_MARY`
> pelos valores reais (nunca commite os valores reais no repositório).

### Gerar hash bcrypt de uma senha

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw('SENHA_AQUI'.encode(), bcrypt.gensalt()).decode())"
```

---

## Ordem de carregamento do auth no app

O app tenta em sequência:

1. `auth/users.yaml` em disco (uso local)
2. `st.secrets["auth"]` (Streamlit Cloud)
3. `AUTH_CONFIG_JSON` como variável de ambiente (Hugging Face / qualquer env)
4. Erro — mostra mensagem e para

---

## packages.txt e requirements.txt

Os mesmos da raiz do repositório são válidos para HF Spaces com runtime Python.
O HF instala `packages.txt` via `apt-get` antes do pip — essencial para PyVista/VTK:

```
libgl1-mesa-glx
libglu1-mesa
xvfb
```
