import math
import os
import sys
import time
import torch

import torchvision.models.detection.mask_rcnn

from coco_utils import get_coco_api_from_dataset
from coco_eval import CocoEvaluator
import utils

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)


def train_one_epoch(model, optimizer, data_loader, device, epoch, print_freq, log_writer):
    model.train()
    metric_logger = utils.MetricLogger(delimiter="  ")
    metric_logger.add_meter('lr', utils.SmoothedValue(window_size=1, fmt='{value:.6f}'))
    header = 'Epoch: [{}]'.format(epoch)

    # lr_scheduler = None
    milestones = [len(data_loader)//2]
    lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=milestones, gamma=0.8)
    # if epoch == 0:
    #     warmup_factor = 1. / 1000
    #     warmup_iters = min(1000, len(data_loader) - 1)
    #
    #     lr_scheduler = utils.warmup_lr_scheduler(optimizer, warmup_iters, warmup_factor)

    count = 0
    for images, targets in metric_logger.log_every(data_loader, print_freq, header):
        count += 1
        images = list(image.to(device) for image in images)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

        loss_dict = model(images, targets)

        losses = sum(loss for loss in loss_dict.values())

        # reduce losses over all GPUs for logging purposes
        loss_dict_reduced = utils.reduce_dict(loss_dict)
        losses_reduced = sum(loss for loss in loss_dict_reduced.values())

        loss_value = losses_reduced.item()

        if not math.isfinite(loss_value):
            print("count {}".format(count))
            print(">>>>>>>>>>>>>>>>>> bboxes")
            print(targets[0]["boxes"])
            print(">>>>>>>>>>>>>>>>>> labels")
            print(targets[0]["labels"])
            print(">>>>>>>>>>>>>>>>>> image_id")
            print(targets[0]["image_id"])
            print(">>>>>>>>>>>>>>>>>> area")
            print(targets[0]["area"])
            print("Loss is {}, stopping training".format(loss_value))
            print(loss_dict_reduced)
            sys.exit(1)

        optimizer.zero_grad()
        losses.backward()
        optimizer.step()

        if lr_scheduler is not None:
            lr_scheduler.step()

        metric_logger.update(loss=losses_reduced, **loss_dict_reduced)
        metric_logger.update(lr=optimizer.param_groups[0]["lr"])

        # ================================================================== #
        #                        Tensorboard Logging                         #
        # ================================================================== #
        if count % 100 == 0:
            n_iter = count + epoch * len(data_loader) / len(images)
            log_writer.add_scalar('Loss/total', loss_value, n_iter/100)
            log_writer.add_scalar('Loss/class', loss_dict['loss_classifier'], n_iter/100)
            log_writer.add_scalar('Loss/bbox', loss_dict['loss_box_reg'], n_iter/100)
            log_writer.add_scalar('Loss/mask', loss_dict['loss_mask'], n_iter/100)
            log_writer.add_scalar('Loss/objectness', loss_dict['loss_objectness'], n_iter/100)
            log_writer.add_scalar('Loss/rpn_box', loss_dict['loss_rpn_box_reg'], n_iter/100)

def _get_iou_types(model):
    model_without_ddp = model
    if isinstance(model, torch.nn.parallel.DistributedDataParallel):
        model_without_ddp = model.module
    iou_types = ["bbox"]
    if isinstance(model_without_ddp, torchvision.models.detection.MaskRCNN):
        iou_types.append("segm")
    if isinstance(model_without_ddp, torchvision.models.detection.KeypointRCNN):
        iou_types.append("keypoints")
    return iou_types


@torch.no_grad()
def evaluate(epoch, model, data_loader, device, log_writer):
    n_threads = torch.get_num_threads()
    # FIXME remove this and make paste_masks_in_image run on the GPU
    torch.set_num_threads(1)
    cpu_device = torch.device("cpu")
    model.eval()
    metric_logger = utils.MetricLogger(delimiter="  ")
    header = 'Test:'

    coco = get_coco_api_from_dataset(data_loader.dataset)
    iou_types = _get_iou_types(model)
    coco_evaluator = CocoEvaluator(coco, iou_types)

    for image, targets in metric_logger.log_every(data_loader, 100, header):
        image = list(img.to(device) for img in image)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

        torch.cuda.synchronize()
        model_time = time.time()
        outputs = model(image)

        outputs = [{k: v.to(cpu_device) for k, v in t.items()} for t in outputs]
        model_time = time.time() - model_time

        res = {target["image_id"].item(): output for target, output in zip(targets, outputs)}
        evaluator_time = time.time()
        coco_evaluator.update(res)
        evaluator_time = time.time() - evaluator_time
        metric_logger.update(model_time=model_time, evaluator_time=evaluator_time)

    # gather the stats from all processes
    metric_logger.synchronize_between_processes()
    print("Averaged stats:", metric_logger)
    coco_evaluator.synchronize_between_processes()

    # accumulate predictions from all images
    coco_evaluator.accumulate()
    eval_result = coco_evaluator.summarize()
    torch.set_num_threads(n_threads)
    # ================================================================== #
    #                        Tensorboard Logging                         #
    # ================================================================== #
    log_writer.add_scalar('bbox/AP|IoU=0.5:0.95', eval_result['bbox'][0], epoch)
    log_writer.add_scalar('bbox/AP|IoU=0.5', eval_result['bbox'][1], epoch)
    log_writer.add_scalar('segm/AP|IoU=0.5:0.95', eval_result['segm'][0], epoch)
    log_writer.add_scalar('segm/AP|IoU=0.5', eval_result['segm'][1], epoch)

    return coco_evaluator
