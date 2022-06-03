NAME   := 878324840923.dkr.ecr.us-east-1.amazonaws.com/airbyte/source-medrio
TAG    := $$(git rev-parse --short HEAD)
IMG    := ${NAME}:${TAG}
LATEST := ${NAME}:latest
DEV    := ${NAME}:dev

build : login
	@echo image=${IMG}
	@docker buildx build . \
    --platform "linux/amd64,linux/arm64" \
	--tag ${IMG} \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
	--tag ${IMG} \
    --load

dev : login
	@echo image=${IMG}
	@docker buildx build . \
    --platform "linux/amd64,linux/arm64" \
	--tag ${IMG} \
    --tag ${DEV} \
    --push
	@docker buildx build . \
    --platform "linux/arm64" \
	--tag ${IMG} \
    --tag ${DEV} \
    --load

login :
	@aws ecr get-login-password | docker login -u AWS 878324840923.dkr.ecr.us-east-1.amazonaws.com --password-stdin
