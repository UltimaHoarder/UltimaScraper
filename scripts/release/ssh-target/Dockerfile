# A disposable "remote host" for installer acceptance: sshd plus its own Docker
# daemon. The deploy user is not in the docker group, so Docker works only
# through sudo with a password, the path most real hosts need.
FROM docker:28-dind@sha256:2a232a42256f70d78e3cc5d2b5d6b3276710a0de0596c145f627ecfae90282ac

ARG DEPLOY_PASSWORD

RUN apk add --no-cache openssh sudo bash \
    && ssh-keygen -A \
    && adduser -D -s /bin/bash deploy \
    && echo "deploy:${DEPLOY_PASSWORD:?Set DEPLOY_PASSWORD}" | chpasswd \
    && echo 'deploy ALL=(ALL) ALL' > /etc/sudoers.d/deploy \
    && chmod 0440 /etc/sudoers.d/deploy \
    # Alpine disables forwarding; the WebUI tunnels to the backend through it.
    && sed -i 's/^AllowTcpForwarding no/AllowTcpForwarding yes/' /etc/ssh/sshd_config \
    && printf 'PasswordAuthentication yes\n' >> /etc/ssh/sshd_config

# Keep the daemon on its Unix socket only.
ENV DOCKER_TLS_CERTDIR=""

EXPOSE 22
ENTRYPOINT ["/bin/sh", "-c", "/usr/sbin/sshd && exec dockerd-entrypoint.sh dockerd"]
