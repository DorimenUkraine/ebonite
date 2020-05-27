import contextlib

import docker.errors
import pytest

from ebonite.core.objects import Image
from ebonite.ext.docker import DockerBuilder, DockerEnv, DockerImage, RemoteRegistry
from tests.build.builder.test_base import SECRET, BuildableMock
from tests.conftest import docker_test

CLEAN = True
IMAGE_NAME = 'ebonite_test_docker_builder_image'
HELLO_WORLD_NAME = 'ebonite_hello_world'


@pytest.fixture
def helloworld_image():
    envs = []

    def factory(docker_env: DockerEnv):
        envs.append(docker_env)
        with docker_env.daemon.client() as c:
            image = c.images.pull('hello-world:latest')  # pull hello-world image
            if isinstance(image, list):
                image = image[0]

            docker_image = DockerImage(f'{HELLO_WORLD_NAME}_{len(envs)}', registry=docker_env.registry)
            image.tag(docker_image.uri)  # tag image as *registry*/ebonite-hello-world
            if isinstance(docker_env.registry, RemoteRegistry):
                c.images.push(docker_image.uri)  # push tag to repository
                c.images.remove(docker_image.uri)  # remove from local registry
        return Image('hello-world', BuildableMock(), 0, docker_image)

    yield factory
    for env in envs:
        with env.daemon.client() as client:
            try:
                client.images.remove('hello-world:latest', force=True)
            except docker.errors.ImageNotFound:
                pass


@pytest.fixture
def docker_builder():
    builder = DockerBuilder()
    build = builder.build_image
    images = []

    def reg_build(buildable, image: DockerImage, environment: DockerEnv,
                  force_overwrite=False, **kwargs):
        images.append((image.name, environment))
        return build(buildable, image, environment, force_overwrite, **kwargs)

    builder.build_image = reg_build

    try:
        yield builder
    finally:
        for image_name, env in images:
            with env.daemon.client() as c:
                try:
                    c.images.remove(image_name, force=True)
                except docker.errors.ImageNotFound:
                    pass


@contextlib.contextmanager
def get_image_output(image_params: DockerImage, env: DockerEnv):
    with env.daemon.client() as client:
        if isinstance(env.registry, RemoteRegistry):
            try:
                # remove to ensure that image was pushed to remote registry,
                # if so following `run` call will pull it back
                client.images.remove(image_params.uri)
            except docker.errors.ImageNotFound:
                pass

        try:
            yield client.containers.run(image_params.uri, remove=True).decode('utf8').strip()
        except docker.errors.ContainerError as e:
            yield e.stderr.decode('utf8')
        finally:
            try:
                client.images.remove(image_params.uri)
            except docker.errors.ImageNotFound:
                pass


def test_docker_builder__create__ok(docker_builder: DockerBuilder, dockerenv_local):
    args = {'name': 'a', 'tag': 'b', 'repository': 'c'}
    image = docker_builder.create_image(environment=dockerenv_local, **args)
    assert isinstance(image, DockerImage)
    assert image == DockerImage(**args)


def test_docker_builder__create__extra_arg(docker_builder: DockerBuilder, dockerenv_local):
    with pytest.raises(TypeError):
        docker_builder.create_image('a', dockerenv_local, kek='b')


@docker_test
@pytest.mark.parametrize('docker_env', ['dockerenv_local', 'dockerenv_remote'])
def test_docker_builder__build__ok(docker_builder: DockerBuilder, docker_env, request):
    docker_env: DockerEnv = request.getfixturevalue(docker_env)
    image = DockerImage(IMAGE_NAME, registry=docker_env.registry)
    docker_builder.build_image(BuildableMock(), image, docker_env, force_overwrite=True)
    assert image.image_id is not None
    with docker_env.daemon.client() as c:
        assert image.exists(c)

    with get_image_output(image, docker_env) as output:
        assert output == SECRET


def test_docker_builder__build__extra_args(docker_builder: DockerBuilder):
    with pytest.raises(TypeError):
        docker_builder.build_image(BuildableMock(), DockerImage(IMAGE_NAME), kekek='a')


@docker_test
@pytest.mark.parametrize('docker_env', ['dockerenv_local', 'dockerenv_remote'])
def test_docker_builder__exists__ok(docker_builder: DockerBuilder, docker_env, helloworld_image, request):
    docker_env: DockerEnv = request.getfixturevalue(docker_env)
    image = helloworld_image(docker_env)

    assert docker_builder.image_exists(image.params, docker_env)


@docker_test
@pytest.mark.parametrize('docker_env', ['dockerenv_local', 'dockerenv_remote'])
def test_docker_builder__exists__not(docker_builder: DockerBuilder, docker_env, request):
    docker_env: DockerEnv = request.getfixturevalue(docker_env)
    image = DockerImage('this__image__is__impossible', 'tag__also__impossible')

    assert not docker_builder.image_exists(image, docker_env)


def test_docker_builder__exists__extra_args(docker_builder: DockerBuilder, dockerenv_local):
    with pytest.raises(TypeError):
        docker_builder.image_exists(DockerImage(IMAGE_NAME), dockerenv_local, kekek='a')


@docker_test
@pytest.mark.parametrize('docker_env', ['dockerenv_local', 'dockerenv_remote'])
def test_docker_builder__delete(docker_builder: DockerBuilder, docker_env, helloworld_image, request):
    docker_env: DockerEnv = request.getfixturevalue(docker_env)
    image = helloworld_image(docker_env).params

    assert docker_builder.image_exists(image, docker_env)
    docker_builder.delete_image(image, docker_env)
    assert not docker_builder.image_exists(image, docker_env)


def test_docker_builder__delete__extra_args(docker_builder: DockerBuilder, dockerenv_local):
    with pytest.raises(TypeError):
        docker_builder.delete_image(DockerImage(IMAGE_NAME), dockerenv_local, kekek='a')
