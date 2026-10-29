# Docker release wheelhouse

Release builds may place first-party wheel artifacts in this directory. Run
`scripts/release/build_docker_wheelhouse.sh` from the repository checkout to
build them from the local release-day sources.

Only this README and its .gitignore are tracked. Generated wheels are ignored by Git and copied
into the Docker build as immutable package artifacts; sibling repositories are
never copied into the image.
