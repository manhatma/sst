FROM golang:1.22-alpine AS build

WORKDIR /go/src/gosst

COPY go.mod ./
COPY go.sum ./
RUN go mod download

COPY . .
RUN go install -v ./cmd/...

FROM alpine:3.20 AS gosst-tcp
WORKDIR /app
COPY --from=build /go/bin/gosst-tcp gosst-tcp
CMD ["./gosst-tcp", \
     "--database", "/data/sst.db", \
     "--host", "0.0.0.0", \
     "--port", "557", \
     "--server", "http://dashboard:5000"]

FROM alpine:3.20 AS gosst-http
WORKDIR /app
COPY --from=build /go/bin/gosst-http gosst-http
CMD ["./gosst-http", \
     "--database", "/data/sst.db", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--server", "http://dashboard:5000"]
