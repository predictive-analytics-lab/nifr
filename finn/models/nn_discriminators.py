import torch
import torch.nn as nn
import torch.nn.functional as F

from finn import layers
from .disc_models import linear_classifier, conv_classifier
from .discriminator_base import DiscBase, compute_log_pz, fetch_model


class NNDisc(DiscBase):
    def __init__(self, args, x_dim, z_dim_flat):
        """Create the discriminators that enfoce the partition on z"""
        if args.dataset == 'adult':
            s_dim = 1
            self.x_s_dim = x_dim + s_dim
            z_channels = z_dim_flat + 1
        elif args.dataset == 'cmnist':
            s_dim = 10
            self.x_s_dim = x_dim  # s is included in x
            z_channels = x_dim * 16

        args.zs_dim = round(args.zs_frac * z_channels)
        if args.meta_learn:
            args.zy_dim = z_channels - args.zs_dim
            args.zn_dim = 0
        else:
            args.zy_dim = round(args.zy_frac * z_channels)
            args.zn_dim = z_channels - args.zs_dim - args.zy_dim

        # =========== Define discriminator networks ============
        if args.dataset == 'adult':
            # ==== MLP models ====
            output_activation = nn.Sigmoid
            hidden_sizes = [400, 400]
            disc_s_from_zs = layers.Mlp([args.zs_dim] + hidden_sizes + [s_dim],
                                        activation=nn.ReLU, output_activation=output_activation)

            hidden_sizes = [400, 400]
            disc_s_from_zy = layers.Mlp([args.zy_dim] + hidden_sizes + [s_dim],
                                        activation=nn.ReLU, output_activation=output_activation)
        else:
            if args.nn_disc == 'linear':
                disc_s_from_zs = linear_classifier(args.zs_dim * 7 * 7, args.s_dim)
                disc_s_from_zy = linear_classifier(args.zy_dim * 7 * 7, args.s_dim)
            else:
                disc_s_from_zs = conv_classifier(args.zs_dim, args.s_dim, 2)
                disc_s_from_zy = conv_classifier(args.zy_dim, args.s_dim, 3)

        disc_s_from_zs.to(args.device)
        disc_s_from_zy.to(args.device)
        self.s_from_zs = disc_s_from_zs
        self.s_from_zy = disc_s_from_zy
        self.pred_s_from_zy_weight = args.pred_s_from_zy_weight
        self.disc_name_list = ['s_from_zs', 's_from_zy']  # for generating discs_dict
        self.args = args

    @property
    def discs_dict(self):
        return {disc_name: getattr(self, disc_name) for disc_name in self.disc_name_list}

    def create_model(self):
        return fetch_model(self.args, self.x_s_dim)

    def assemble_whole_model(self, trunk):
        return trunk

    def compute_loss(self, x, s, y, model, return_z=False):

        zero = x.new_zeros(x.size(0), 1)

        if self.args.dataset == 'cmnist':
            # loss_fn = F.l1_loss
            loss_fn = F.nll_loss
        else:
            loss_fn = F.binary_cross_entropy
            x = torch.cat((x, s.float()), dim=1)

        z, delta_logp = model(x, zero)  # run model forward

        log_pz = compute_log_pz(z)
        # zn = z[:, :self.args.zn_dim]
        zs = z[:, self.args.zn_dim: (z.size(1) - self.args.zy_dim)]
        zy = z[:, (z.size(1) - self.args.zy_dim):]
        # Enforce independence between the fair representation, zy,
        #  and the sensitive attribute, s
        pred_s_from_zy_loss = z.new_zeros(1)
        pred_s_from_zs_loss = z.new_zeros(1)

        if self.s_from_zy is not None and zy.size(1) > 0:
            if self.args.entropy_loss_weight != 0:
                pred_s_from_zy = self.s_from_zy(
                    layers.grad_reverse(zy, lambda_=self.args.entropy_loss_weight))
                # the adversarial discriminator will try to minimize the entropy
                entropy = -(pred_s_from_zy * pred_s_from_zy.exp()).sum() / x.size(0)
                pred_s_from_zy_loss += entropy
                zy = zy.detach().clone()  # detach so that the NLL loss doesn't go through trunk
            else:
                # if we don't use the entropy loss, we don't detach and reverse the gradient on z_yn
                zy = layers.grad_reverse(zy, lambda_=self.pred_s_from_zy_weight)

            pred_s_from_zy_loss += loss_fn(self.s_from_zy(zy), s, reduction='mean')
        # Enforce independence between the fair, zy, and unfair, zs, partitions

        if self.s_from_zs is not None and zs.size(1) > 0:
            pred_s_from_zs_loss = (self.args.pred_s_from_zs_weight
                                   * loss_fn(self.s_from_zs(zs), s, reduction='mean'))

        log_px = self.args.log_px_weight * (log_pz - delta_logp).mean()
        loss = -log_px + pred_s_from_zs_loss + pred_s_from_zy_loss

        if return_z:
            return loss, z
        return (loss, -log_px, z.new_zeros(1), self.pred_s_from_zy_weight * pred_s_from_zy_loss,
                pred_s_from_zs_loss)
