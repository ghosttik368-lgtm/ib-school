FROM docker:29-dind
COPY runner/ /opt/ib-runner/
COPY deploy/onebox/runner-entry.sh /usr/local/bin/ib-runner-entry
ENTRYPOINT ["sh", "/usr/local/bin/ib-runner-entry"]
