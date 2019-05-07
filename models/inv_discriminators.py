from collections import namedtuple
import math

import torch
import torch.nn.functional as F

import layers
import models
from utils.training_utils import fetch_model
from .nn_discriminators import compute_log_pz

Discriminators = namedtuple('Discriminators', ['s_from_zs', 'y_from_zy'])


def make_networks(args, x_dim, z_dim_flat):
    """Create the discriminators that enfoce the partition on z"""
    if args.dataset == 'adult':
        z_dim_flat += 1
        args.zs_dim = round(args.zs_frac * z_dim_flat)
        args.zyn_dim = z_dim_flat - args.zs_dim
        s_dim = 1
        x_dim += s_dim

        disc_y_from_zy = models.tabular_model(args, input_dim=args.zyn_dim)
        disc_s_from_zs = models.tabular_model(args, input_dim=args.zs_dim)
        disc_y_from_zy.to(args.device)
    else:
        z_channels = x_dim * 4 * 4
        wh = z_dim_flat // z_channels
        args.zs_dim = round(args.zs_frac * z_channels)
        args.zyn_dim = z_channels - args.zs_dim

        if not args.meta_learn:
            disc_y_from_zy = models.tabular_model(args, input_dim=(wh * args.zyn_dim))  # logs-softmax
            disc_y_from_zy.to(args.device)
        else:
            args.zyn_dim = z_channels - args.zs_dim

            disc_y_from_zy = None

        # logistic output
        disc_s_from_zs = models.tabular_model(args, input_dim=(wh * args.zs_dim))

    disc_s_from_zs.to(args.device)
    discs = Discriminators(s_from_zs=disc_s_from_zs, y_from_zy=disc_y_from_zy)

    return fetch_model(args, x_dim), discs


def assemble_whole_model(args, trunk, discs):
    chain = [trunk]
    chain += [layers.MultiHead([discs.y_from_zy, discs.s_from_zs],
                               split_dim=[args.zyn_dim, args.zs_dim])]
    return layers.SequentialFlow(chain)


def compute_loss(args, x, s, y, model, discs, return_z=False):
    whole_model = assemble_whole_model(args, model, discs)
    zero = x.new_zeros(x.size(0), 1)

    if args.dataset == 'cmnist':

        def class_loss(_logits, _target):
            _preds = F.log_softmax(_logits[:, :10], dim=1)
            return F.nll_loss(_preds, _target, reduction='mean')

    else:
        def class_loss(_logits, _target):
            return F.binary_cross_entropy_with_logits(_logits[:, :1], reduction='mean')

        x = torch.cat((x, s.float()), dim=1)

    z, delta_logp = whole_model(x, zero)  # run model forward

    log_pz = 0
    # zn = z[:, :args.zn_dim]
    wh = z.size(1) // (args.zyn_dim + args.zs_dim)
    zy, zs = z.split(split_size=[args.zyn_dim * wh, args.zs_dim * wh], dim=1)

    # Enforce independence between the fair representation, zy,
    #  and the sensitive attribute, s
    pred_y_loss = z.new_zeros(1)
    pred_s_from_zs_loss = z.new_zeros(1)

    if zy.size(1) > 0:
        log_pz += compute_log_pz(zy)
        if not args.meta_learn:
            pred_y_loss = args.pred_y_weight * class_loss(zy, y)

    if zs.size(1) > 0:
        log_pz += compute_log_pz(zs)
        pred_s_from_zs_loss = args.pred_s_from_zs_weight * class_loss(zs, s)

    log_px = args.log_px_weight * (log_pz - delta_logp).mean()
    loss = -log_px + pred_y_loss + pred_s_from_zs_loss

    if return_z:
        return loss, z

    return loss, -log_px, pred_y_loss, z.new_zeros(1), pred_s_from_zs_loss
