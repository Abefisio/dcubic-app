# Decisão: app.dcubic pelo proxy da Cloudflare

**Data:** 29/10/2026
**Decisão:** o domínio `app.dcubic.reloadcursos.com` passa a ser servido pelo proxy da Cloudflare (nuvem laranja), com SSL **Full (strict)**.

## Motivo

O envio de STL grande era limitado pela rede entre o Brasil e a VPS em Frankfurt (RTT ~220 ms; uma conexão sobe 1,0–1,7 MB/s). Com o proxy, o navegador envia para a borda da Cloudflare em São Paulo, e a Cloudflare leva os dados até a VPS.

## Medição (29/10/2026, Mac do Dr. Abe → VPS, 4 partes em paralelo, SHA-256 conferido)

| Teste | Direto | Pela Cloudflare | Ganho |
|---|---|---|---|
| 300 MiB (3 rodadas) | 2:02 (2,70 MB/s) | 0:31 (10,79 MB/s) | 3,9× |
| 3 GB | 24:03 (2,23 MB/s, 2 rodadas) | 4:24 (12,45 MB/s, 1 rodada) | 5,4× |
| Quedas de conexão em 3 GB | 17 | nenhuma | — |

O certificado Let's Encrypt (HTTP-01) foi emitido normalmente com o proxy ativo.

Relatório completo: `~/Desktop/RELATORIOS-CLAUDE/cloudflare-teste-medicao.txt`.

## Alterações no painel Cloudflare (zona reloadcursos.com)

1. Configuration Rule "app.dcubic Full strict": `http.host eq "app.dcubic.reloadcursos.com"` → SSL Full (strict).
2. Registro A `app.dcubic` → `152.239.113.183` passou de DNS only (nuvem cinza) para Proxied (nuvem laranja).
3. Registros de teste `teste-envio.dcubic` e `teste-envio-direto.dcubic` apagados.

"Always Use HTTPS" permanece **desligado**. É o que permite a renovação do certificado por HTTP-01 na porta 80. Nada foi alterado na VPS.

## Cuidados

- Não ligar "Always Use HTTPS" nem criar redirect http→https na Cloudflare para `*.dcubic`: isso quebra a renovação do certificado de origem (vence em 27/01/2027 e o Traefik renova sozinho).
- Partes de envio devem ficar abaixo de 100 MB (limite por pedido do plano gratuito). Hoje elas têm até 32 MiB.
- Rocket Loader e Bot Fight Mode devem permanecer desligados.

## Como reverter

No painel Cloudflare → reloadcursos.com → DNS → Records, mudar `app.dcubic` de volta para **nuvem cinza (DNS only)**. A mudança vale em segundos e se completa em até ~5 min. Nada precisa ser feito na VPS. A Configuration Rule pode ficar, porque não tem efeito com a nuvem cinza.
