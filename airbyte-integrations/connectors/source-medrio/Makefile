NAME   := 878324840923.dkr.ecr.us-east-1.amazonaws.com/airbyte/source-medrio
TAG    := $$(git rev-parse --short HEAD)
IMG    := ${NAME}:${TAG}
LATEST := ${NAME}:latest
DEV    := ${NAME}:dev

build : login
	@echo image=${IMG}
	@docker buildx build . \
    --platform "linux/amd64,linux/arm64" \
    --tag ${LATEST} \
    --push
	@docker buildx build . \
    --platform "linux/amd64" \
    --tag ${LATEST}-amd \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
    --tag ${LATEST}-arm \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
    --tag ${LATEST} \
    --load

dev : login
	@echo image=${IMG}
	@docker buildx build . \
    --platform "linux/amd64,linux/arm64" \
    --tag ${DEV} \
    --push
	@docker buildx build . \
    --platform "linux/amd64" \
    --tag ${DEV}-amd \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
    --tag ${DEV}-arm \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
    --tag ${DEV} \
    --load

login :
	@aws ecr get-login-password | docker login -u AWS 878324840923.dkr.ecr.us-east-1.amazonaws.com --password-stdin
