# Refinamento do Canal/Raiz do Molar — DCubic Image System Platform

_Sessão de 30/08/2026. Documenta o estado para retomada futura._

## Objetivo
Um único controle (slider) acoplado: reduzir a opacidade da Dentina (camada externa, translúcida) aumenta automaticamente o preenchimento/opacidade do canal/raiz (molar_sup__raiz_voi_, interno), como se um preenchesse o espaço que o outro libera. Combinado com um plano de corte mesial (clip plane) fixo, para revelar o interior em secção transversal — replicando o enquadramento das imagens de referência reais de microtomografia.

## Referências de imagem (~/Desktop/DCUBIC-SITE/MICROTOMO)
- **palatino.jpg** — referência ANATÔMICA correta: mostra os 3 canais finos e ramificados do molar (um por raiz), em azul-violeta (~#8282DC), dentro de casca cinza translúcida. É o alvo de forma.
- **"Dente 11 - Visao Mesial - Canal opacidade 100% - Ctvol.jpg"** e **"Dente 11 - Vestibular - Sem cor - Ctvol.jpg"** — são de OUTRO dente (incisivo, raiz única). Servem só como referência de ESTILO (como opacidade+corte revelam o canal), não como forma-alvo — não têm a anatomia de 3 raízes do molar.

## Escopo de estruturas
Restrito a 2: Dentina.stl (translúcida, externa) + molar_sup__raiz_voi_.stl (canal/raiz, interno). Esmalte.stl fora do foco atual.

## Abordagem técnica validada
molar_sup__raiz_voi_.stl é o corpo sólido inteiro da raiz (não tem o canal como malha isolada). Abordagem: erosão morfológica progressiva do volume voxelizado (scipy binary_erosion) sobre o volume derivado — NUNCA sobre o STL original, que fica intocado. Erosão confirmada funcionando numericamente: 0 iter = 400.283 voxels, 5 iter = 116.046 voxels, 10 iter = 11.034 voxels (redução real, não só visual).

## Problema identificado e corrigido nesta sessão
Erosão sozinha (sem corte) não é visualmente perceptível de fora — o núcleo erodido, mesmo menor, segue a mesma forma externa e fica escondido atrás da Dentina. Solução: combinar erosão com plano de corte mesial (clip plane), replicando o enquadramento das referências reais.

## Bug de biblioteca encontrado
Plotly 6.9.0: fig.frames não é incluído no HTML gerado por write_html() (bug/mudança de comportamento — frames count = 0 no output final, mesmo existindo em to_json()). Isso quebrava o slider interativo (método "animate" sem frames para animar). Correção aplicada: trocar para método "restyle" com toggling de visible por trace (todas as N traces geradas, slider alterna visibilidade), que não depende de frames.

## Estado ao final da sessão (30/08, pendente de teste)
- Commit local feito na branch teste/frenteB-corte (887f126), sem push.
- Arquivo interativo em ~/Desktop/dcubic_preview_frenteB.html, versão corrigida (restyle+visible) gerada, AINDA NÃO TESTADA por Dr. Abe.
- Frente A (teste/frenteA-solido) está PAUSADA — teve um desvio de escopo (tentativa de gerar hash bcrypt para autenticação, negada) e precisa de revisão antes de retomar.

## Próximos passos ao retomar
1. Dr. Abe testa o slider em ~/Desktop/dcubic_preview_frenteB.html (recarregar com Cmd+Shift+R para evitar cache).
2. Se o corte mesial + erosão acoplada bater com palatino.jpg, aprovar e integrar em app.py de produção (ainda sem deploy).
3. Decidir se a Frente A (preenchimento sólido) é descartada ou revisada, já que a Frente B com corte mesial parece o caminho mais promissor.
4. Deploy (push para main) só depois de aprovação visual explícita — app precisa estar funcional para demonstração à professora da universidade.
