FROM node:24.5.0-alpine3.22@sha256:e8e882c692a08878d55ec8ff6c5a4a71b3edca25eda0af4406e2a160d8a93cf2 AS web-build
WORKDIR /web
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY frontend ./
RUN pnpm run build

FROM caddy:2.10.0-alpine@sha256:ae4458638da8e1a91aafffb231c5f8778e964bca650c8a8cb23a7e8ac557aa3c
COPY --from=web-build /web/dist /srv
# Resmî image düşük portlar için cap_net_bind_service taşır. Bu deployment
# 8443 kullanır; no-new-privileges + cap_drop ALL ile exec EPERM oluşmaması
# için gereksiz file capability kaldırılır.
RUN setcap -r /usr/bin/caddy
# Bu sabitlenmiş image /etc/passwd içinde "caddy" kullanıcısı taşımıyor.
# Compose tüm Linux capability'lerini düşürür; root yalnız root-owned Caddy
# data/config volume'larına yazabilmek için kullanılır.
USER 0:0
