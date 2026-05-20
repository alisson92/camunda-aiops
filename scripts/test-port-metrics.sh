for item in \
  "camunda-connectors:http:8080" \
  "camunda-identity:metrics:8082" \
  "camunda-optimize:management:8092" \
  "camunda-web-modeler-restapi:http-management:8081"; do

  svc=$(echo $item | cut -d: -f1)
  port=$(echo $item | cut -d: -f3)

  pod=$(kubectl get pod -n camunda -l "app.kubernetes.io/component=$(echo $svc | sed 's/camunda-//')" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

  if [ -z "$pod" ]; then
    echo "=== $svc === POD NÃO ENCONTRADO"
    continue
  fi

  echo "=== $svc (pod: $pod, porta: $port) ==="
  result=$(kubectl exec -n camunda "$pod" -- \
    wget -qO- --timeout=5 "http://localhost:${port}/actuator/prometheus" 2>/dev/null | head -3)

  if [ -n "$result" ]; then
    echo "  ✓ Endpoint responde:"
    echo "$result" | sed 's/^/    /'
  else
    echo "  ✗ Sem resposta em /actuator/prometheus"
    result2=$(kubectl exec -n camunda "$pod" -- \
      wget -qO- --timeout=5 "http://localhost:${port}/metrics" 2>/dev/null | head -3)
    if [ -n "$result2" ]; then
      echo "  ✓ Responde em /metrics:"
      echo "$result2" | sed 's/^/    /'
    fi
  fi
  echo ""
done
