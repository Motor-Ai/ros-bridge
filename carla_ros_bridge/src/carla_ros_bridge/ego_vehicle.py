#!/usr/bin/env python

#
# Copyright (c) 2018-2020 Intel Corporation
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.
#
"""
Classes to handle Carla vehicles
"""
import math

import numpy
from carla import VehicleControl
from carla_msgs.msg import (
    CarlaEgoVehicleInfo,
    CarlaEgoVehicleInfoWheel,
    CarlaEgoVehicleControl,
    CarlaEgoVehicleStatus,
)
from carla_ros_bridge.vehicle import Vehicle
from geometry_msgs.msg import PoseStamped
from ros_compatibility.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import Bool  # pylint: disable=import-error
from std_msgs.msg import ColorRGBA  # pylint: disable=import-error
from scipy.spatial.transform import Rotation

from localization_msgs.msg import Canbus


class EgoVehicle(Vehicle):

    """
    Vehicle implementation details for the ego vehicle
    """

    def __init__(
        self, uid, name, parent, node, carla_actor, vehicle_control_applied_callback
    ):
        """
        Constructor

        :param uid: unique identifier for this object
        :type uid: int
        :param name: name identiying this object
        :type name: string
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: CompatibleNode
        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        """
        super(EgoVehicle, self).__init__(
            uid=uid, name=name, parent=parent, node=node, carla_actor=carla_actor
        )

        self.vehicle_info_published = False
        self.vehicle_control_override = False
        self._vehicle_control_applied_callback = vehicle_control_applied_callback

        self.vehicle_status_publisher = node.new_publisher(
            CarlaEgoVehicleStatus,
            self.get_topic_prefix() + "/vehicle_status",
            qos_profile=10,
        )
        self.vehicle_info_publisher = node.new_publisher(
            CarlaEgoVehicleInfo,
            self.get_topic_prefix() + "/vehicle_info",
            qos_profile=QoSProfile(
                depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL
            ),
        )

        self.control_subscriber = node.new_subscription(
            CarlaEgoVehicleControl,
            self.get_topic_prefix() + "/vehicle_control_cmd",
            lambda data: self.control_command_updated(data, manual_override=False),
            qos_profile=10,
        )

        self.ego_location_publisher = node.new_publisher(
            PoseStamped, self.get_topic_prefix() + "/vehicle_location", qos_profile=10
        )

        self.manual_control_subscriber = node.new_subscription(
            CarlaEgoVehicleControl,
            self.get_topic_prefix() + "/vehicle_control_cmd_manual",
            lambda data: self.control_command_updated(data, manual_override=True),
            qos_profile=10,
        )

        self.canbus_publisher = node.new_publisher(
            Canbus, self.get_topic_prefix() + "/canbus", qos_profile=10
        )

        self.control_override_subscriber = node.new_subscription(
            Bool,
            self.get_topic_prefix() + "/vehicle_control_manual_override",
            self.control_command_override,
            qos_profile=QoSProfile(
                depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL
            ),
        )

        self.enable_autopilot_subscriber = node.new_subscription(
            Bool,
            self.get_topic_prefix() + "/enable_autopilot",
            self.enable_autopilot_updated,
            qos_profile=10,
        )

    def get_marker_color(self):
        """
        Function (override) to return the color for marker messages.

        The ego vehicle uses a different marker color than other vehicles.

        :return: the color used by a ego vehicle marker
        :rtpye : std_msgs.msg.ColorRGBA
        """
        color = ColorRGBA()
        color.r = 0.0
        color.g = 255.0
        color.b = 0.0
        return color

    # ! /usr/bin/env python3

    # This program converts Euler angles to a quaternion.
    # Author: AutomaticAddison.com

    def get_quaternion_from_euler(self, roll, pitch, yaw):
        """
        Convert an Euler angle to a quaternion.

        Input
          :param roll: The roll (rotation around x-axis) angle in radians.
          :param pitch: The pitch (rotation around y-axis) angle in radians.
          :param yaw: The yaw (rotation around z-axis) angle in radians.

        Output
          :return qx, qy, qz, qw: The orientation in quaternion [x,y,z,w] format
        """
        qx = numpy.sin(roll / 2) * numpy.cos(pitch / 2) * numpy.cos(
            yaw / 2
        ) - numpy.cos(roll / 2) * numpy.sin(pitch / 2) * numpy.sin(yaw / 2)
        qy = numpy.cos(roll / 2) * numpy.sin(pitch / 2) * numpy.cos(
            yaw / 2
        ) + numpy.sin(roll / 2) * numpy.cos(pitch / 2) * numpy.sin(yaw / 2)
        qz = numpy.cos(roll / 2) * numpy.cos(pitch / 2) * numpy.sin(
            yaw / 2
        ) - numpy.sin(roll / 2) * numpy.sin(pitch / 2) * numpy.cos(yaw / 2)
        qw = numpy.cos(roll / 2) * numpy.cos(pitch / 2) * numpy.cos(
            yaw / 2
        ) + numpy.sin(roll / 2) * numpy.sin(pitch / 2) * numpy.sin(yaw / 2)

        return qx, qy, qz, qw

    def send_vehicle_msgs(self, frame, timestamp):
        """
        send messages related to vehicle status

        :return:
        """
        vehicle_status = CarlaEgoVehicleStatus(
            header=self.get_msg_header("map", timestamp=timestamp)
        )
        vehicle_status.velocity = self.get_vehicle_speed_abs(self.carla_actor)
        vehicle_status.acceleration.linear = self.get_current_ros_accel().linear
        vehicle_status.orientation = self.get_current_ros_pose().orientation
        vehicle_status.control.throttle = self.carla_actor.get_control().throttle
        vehicle_status.control.steer = self.carla_actor.get_control().steer
        vehicle_status.control.brake = self.carla_actor.get_control().brake
        vehicle_status.control.hand_brake = self.carla_actor.get_control().hand_brake
        vehicle_status.control.reverse = self.carla_actor.get_control().reverse
        vehicle_status.control.gear = self.carla_actor.get_control().gear
        vehicle_status.control.manual_gear_shift = (
            self.carla_actor.get_control().manual_gear_shift
        )
        self.vehicle_status_publisher.publish(vehicle_status)

        ego_loc = PoseStamped(header=self.get_msg_header("map", timestamp=timestamp))
        ego_transform = self.carla_actor.get_transform()
        ego_loc.pose.position.x = ego_transform.location.x
        ego_loc.pose.position.y = ego_transform.location.y
        ego_loc.pose.position.z = ego_transform.location.z
        cy = math.cos(ego_transform.rotation.yaw * 0.5)
        sy = math.sin(ego_transform.rotation.yaw * 0.5)
        cp = math.cos(0)
        sp = math.sin(0)
        cr = math.cos(0)
        sr = math.sin(0)

        ego_loc.pose.orientation = self.get_current_ros_pose().orientation

        canbus_msg = Canbus(
            header=self.get_msg_header("map", timestamp=timestamp),
            steering=vehicle_status.control.steer,
            throttle=vehicle_status.control.throttle,
            speed=vehicle_status.velocity,
            brake=vehicle_status.control.brake,
            accel=vehicle_status.acceleration.linear.x,
            checksum=1,
        )
        self.canbus_publisher.publish(canbus_msg)
        # ego_loc.pose.orientation.x, ego_loc.pose.orientation.y,  ego_loc.pose.orientation.z, ego_loc.pose.orientation.w = self.get_quaternion_from_euler(ego_transform.rotation.roll, ego_transform.rotation.pitch, ego_transform.rotation.yaw)
        self.ego_location_publisher.publish(ego_loc)

        # only send vehicle once (in latched-mode)
        if not self.vehicle_info_published:
            self.vehicle_info_published = True
            vehicle_info = CarlaEgoVehicleInfo()
            vehicle_info.id = self.carla_actor.id
            vehicle_info.type = self.carla_actor.type_id
            vehicle_info.rolename = self.carla_actor.attributes.get("role_name")
            vehicle_physics = self.carla_actor.get_physics_control()

            for wheel in vehicle_physics.wheels:
                wheel_info = CarlaEgoVehicleInfoWheel()
                wheel_info.tire_friction = wheel.tire_friction
                wheel_info.damping_rate = wheel.damping_rate
                wheel_info.max_steer_angle = math.radians(wheel.max_steer_angle)
                wheel_info.radius = wheel.radius
                wheel_info.max_brake_torque = wheel.max_brake_torque
                wheel_info.max_handbrake_torque = wheel.max_handbrake_torque

                inv_T = numpy.array(
                    self.carla_actor.get_transform().get_inverse_matrix(), dtype=float
                )
                wheel_pos_in_map = numpy.array(
                    [
                        wheel.position.x / 100.0,
                        wheel.position.y / 100.0,
                        wheel.position.z / 100.0,
                        1.0,
                    ]
                )
                wheel_pos_in_ego_vehicle = numpy.matmul(inv_T, wheel_pos_in_map)
                wheel_info.position.x = wheel_pos_in_ego_vehicle[0]
                wheel_info.position.y = -wheel_pos_in_ego_vehicle[1]
                wheel_info.position.z = wheel_pos_in_ego_vehicle[2]
                vehicle_info.wheels.append(wheel_info)

            vehicle_info.max_rpm = vehicle_physics.max_rpm
            vehicle_info.max_rpm = vehicle_physics.max_rpm
            vehicle_info.moi = vehicle_physics.moi
            vehicle_info.damping_rate_full_throttle = (
                vehicle_physics.damping_rate_full_throttle
            )
            vehicle_info.damping_rate_zero_throttle_clutch_engaged = (
                vehicle_physics.damping_rate_zero_throttle_clutch_engaged
            )
            vehicle_info.damping_rate_zero_throttle_clutch_disengaged = (
                vehicle_physics.damping_rate_zero_throttle_clutch_disengaged
            )
            vehicle_info.use_gear_autobox = vehicle_physics.use_gear_autobox
            vehicle_info.gear_switch_time = vehicle_physics.gear_switch_time
            vehicle_info.clutch_strength = vehicle_physics.clutch_strength
            vehicle_info.mass = vehicle_physics.mass
            vehicle_info.drag_coefficient = vehicle_physics.drag_coefficient
            vehicle_info.center_of_mass.x = vehicle_physics.center_of_mass.x
            vehicle_info.center_of_mass.y = vehicle_physics.center_of_mass.y
            vehicle_info.center_of_mass.z = vehicle_physics.center_of_mass.z

            self.vehicle_info_publisher.publish(vehicle_info)

    def update(self, frame, timestamp):
        """
        Function (override) to update this object.

        On update ego vehicle calculates and sends the new values for VehicleControl()

        :return:
        """
        self.send_vehicle_msgs(frame, timestamp)
        super(EgoVehicle, self).update(frame, timestamp)

    def destroy(self):
        """
        Function (override) to destroy this object.

        Terminate ROS subscriptions
        Finally forward call to super class.

        :return:
        """
        self.node.logdebug("Destroy Vehicle(id={})".format(self.get_id()))
        self.node.destroy_subscription(self.control_subscriber)
        self.node.destroy_subscription(self.enable_autopilot_subscriber)
        self.node.destroy_subscription(self.control_override_subscriber)
        self.node.destroy_subscription(self.manual_control_subscriber)
        self.node.destroy_publisher(self.vehicle_status_publisher)
        self.node.destroy_publisher(self.vehicle_info_publisher)
        Vehicle.destroy(self)

    def control_command_override(self, enable):
        """
        Set the vehicle control mode according to ros topic
        """
        self.vehicle_control_override = enable.data

    def control_command_updated(self, ros_vehicle_control, manual_override):
        """
        Receive a CarlaEgoVehicleControl msg and send to CARLA

        This function gets called whenever a ROS CarlaEgoVehicleControl is received.
        If the mode is valid (either normal or manual), the received ROS message is
        converted into carla.VehicleControl command and sent to CARLA.
        This bridge is not responsible for any restrictions on velocity or steering.
        It's just forwarding the ROS input to CARLA

        :param manual_override: manually override the vehicle control command
        :param ros_vehicle_control: current vehicle control input received via ROS
        :type ros_vehicle_control: carla_msgs.msg.CarlaEgoVehicleControl
        :return:
        """
        if manual_override == self.vehicle_control_override:
            vehicle_control = VehicleControl()
            vehicle_control.hand_brake = ros_vehicle_control.hand_brake
            vehicle_control.brake = ros_vehicle_control.brake
            vehicle_control.steer = ros_vehicle_control.steer
            vehicle_control.throttle = ros_vehicle_control.throttle
            vehicle_control.reverse = ros_vehicle_control.reverse
            vehicle_control.manual_gear_shift = ros_vehicle_control.manual_gear_shift
            vehicle_control.gear = ros_vehicle_control.gear
            self.carla_actor.apply_control(vehicle_control)
            self._vehicle_control_applied_callback(self.get_id())

    def enable_autopilot_updated(self, enable_auto_pilot):
        """
        Enable/disable auto pilot

        :param enable_auto_pilot: should the autopilot be enabled?
        :type enable_auto_pilot: std_msgs.Bool
        :return:
        """
        self.node.logdebug(
            "Ego vehicle: Set autopilot to {}".format(enable_auto_pilot.data)
        )
        self.carla_actor.set_autopilot(enable_auto_pilot.data)

    @staticmethod
    def get_vector_length_squared(carla_vector):
        """
        Calculate the squared length of a carla_vector
        :param carla_vector: the carla vector
        :type carla_vector: carla.Vector3D
        :return: squared vector length
        :rtype: float64
        """
        return (
            carla_vector.x * carla_vector.x
            + carla_vector.y * carla_vector.y
            + carla_vector.z * carla_vector.z
        )

    @staticmethod
    def get_vehicle_speed_squared(carla_vehicle):
        """
        Get the squared speed of a carla vehicle
        :param carla_vehicle: the carla vehicle
        :type carla_vehicle: carla.Vehicle
        :return: squared speed of a carla vehicle [(m/s)^2]
        :rtype: float64
        """
        return EgoVehicle.get_vector_length_squared(carla_vehicle.get_velocity())

    @staticmethod
    def get_vehicle_speed_abs(carla_vehicle):
        """
        Get the absolute speed of a carla vehicle
        :param carla_vehicle: the carla vehicle
        :type carla_vehicle: carla.Vehicle
        :return: speed of a carla vehicle [m/s >= 0]
        :rtype: float64
        """
        speed = math.sqrt(EgoVehicle.get_vehicle_speed_squared(carla_vehicle))
        return speed
