from pathlib import Path
from typing import Tuple

import torch
from torch import nn
import torchvision
import wandb

from nosinn.configs import SharedArgs, NosinnArgs
from nosinn.utils import wandb_log

__all__ = ["get_data_dim", "log_images"]


def get_data_dim(data_loader) -> Tuple[int, ...]:
    x, _, _ = next(iter(data_loader))
    x_dim = x.shape[1:]

    return tuple(x_dim)


def log_images(
    args: SharedArgs, image_batch, name, step, nsamples=64, nrows=8, monochrome=False, prefix=None
):
    """Make a grid of the given images, save them in a file and log them with W&B"""
    prefix = "train_" if prefix is None else f"{prefix}_"
    images = image_batch[:nsamples]

    if args.dataset == "celeba":
        images = 0.5 * images + 0.5

    if monochrome:
        images = images.mean(dim=1, keepdim=True)
    # torchvision.utils.save_image(images, f'./experiments/finn/{prefix}{name}.png', nrow=nrows)
    shw = torchvision.utils.make_grid(images, nrow=nrows).clamp(0, 1).cpu()
    wandb_log(
        args,
        {prefix + name: [wandb.Image(torchvision.transforms.functional.to_pil_image(shw))]},
        step=step,
    )


def save_model(args, save_dir: Path, model: nn.Module, disc_ensemble, epoch: int, sha: str) -> Path:
    filename = save_dir / "checkpt.pth"
    save_dict = {
        "args": args.as_dict(),
        "sha": sha,
        "model": model.state_dict(),
        "disc_ensemble": disc_ensemble.state_dict(),
        "epoch": epoch,
    }

    torch.save(save_dict, filename)

    return filename


def restore_model(args: NosinnArgs, filename: Path, inn, disc_ensemble):
    chkpt = torch.load(filename, map_location=lambda storage, loc: storage)
    args_chkpt = chkpt["args"]
    assert args.levels == args_chkpt["levels"]
    assert args.level_depth == args_chkpt["level_depth"]
    assert args.coupling_channels == args_chkpt["coupling_channels"]
    assert args.coupling_depth == args_chkpt["coupling_depth"]

    inn.load_state_dict(chkpt["model"])
    disc_ensemble.load_state_dict(chkpt["disc_ensemble"])

    return inn, disc_ensemble
