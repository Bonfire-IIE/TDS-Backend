from app.services.appimage import normalize_kuscia_fields, parse_config


def test_normalize_cr_yaml_fields_for_kuscia_api():
    source = [{
        "restartPolicy": "Never",
        "containers": [{
            "imagePullPolicy": "IfNotPresent",
            "configVolumeMounts": [{"mountPath": "/data/x", "subPath": "x"}],
        }],
    }]

    assert normalize_kuscia_fields(source) == [{
        "restart_policy": "Never",
        "containers": [{
            "image_pull_policy": "IfNotPresent",
            "config_volume_mounts": [{"mount_path": "/data/x", "sub_path": "x"}],
        }],
    }]


def test_parse_appimage_yaml_preserves_config_filenames():
    result = parse_config("""
kind: AppImage
metadata:
  name: demo-image
spec:
  image: {name: docker.io/example/demo, tag: latest}
  configTemplates:
    task-config.conf: "{{.TASK_ID}}"
  deployTemplates:
    - name: demo
      restartPolicy: Never
      containers:
        - name: demo
          imagePullPolicy: IfNotPresent
""", "appimage")

    assert result["name"] == "demo-image"
    assert result["deploy_templates"][0]["restart_policy"] == "Never"
    assert result["deploy_templates"][0]["containers"][0]["image_pull_policy"] == "IfNotPresent"
    assert result["config_templates"] == {"task-config.conf": "{{.TASK_ID}}"}
